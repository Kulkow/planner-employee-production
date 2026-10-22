"""Durable archive of terminal jobs and queryable calculation statistics."""

import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from planner.application.planning import PlanningRequest
from planner.domain.jobs import JobStatus, PlanningJob
from planner.infrastructure.serialization import JOB_CODEC, REQUEST_CODEC


class PostgresPlanningArchive:
    def __init__(self, dsn: str):
        self._dsn = dsn

    @classmethod
    def from_env(cls):
        dsn = os.environ.get('DATABASE_URL')
        return cls(dsn) if dsn else None

    def connect(self):
        return psycopg.connect(self._dsn, connect_timeout=5, row_factory=dict_row)

    def initialize(self):
        migrations = sorted(Path(__file__).with_name('sql').glob('*.sql'))
        with self.connect() as conn:
            conn.execute('SELECT pg_advisory_xact_lock(68430191)')
            for migration in migrations:
                conn.execute(migration.read_text())

    def save(self, job: PlanningJob, request: PlanningRequest):
        if job.status not in (JobStatus.COMPLETED, JobStatus.FAILED) or job.finished_at is None:
            raise ValueError('Only terminal jobs can be archived')
        metrics, plan = job.metrics, job.result
        operations = plan.operations if plan else ()
        departments = {operation.department_name for operation in operations}
        values = {
            'id': job.id, 'status': job.status.value, 'product_card_id': job.task.product_card_id,
            'quantity': job.task.count, 'created_at': job.created_at, 'started_at': job.started_at,
            'finished_at': job.finished_at,
            'calculation_seconds': metrics.elapsed_seconds if metrics else job.duration_sec,
            'memory_start_bytes': metrics.memory_start_bytes if metrics else None,
            'peak_rss_bytes': metrics.peak_rss_bytes if metrics else None,
            'memory_scope': metrics.memory_scope if metrics else 'process',
            'memory_growth_bytes': metrics.peak_rss_bytes - metrics.memory_start_bytes if metrics else None,
            'department_count': len(job.department_results), 'operation_count': len(operations),
            'plan_makespan_seconds': plan.makespan_sec if plan else None,
            'plan_work_seconds': sum(operation.duration_sec for operation in operations) if plan else None,
            'selected_department': next(iter(departments)) if len(departments) == 1 else None,
            'job_json': Jsonb(JOB_CODEC.dump_python(job, mode='json')),
            'request_json': Jsonb(REQUEST_CODEC.dump_python(request, mode='json')),
        }
        # Column names come exclusively from this static dictionary, never input.
        columns = list(values)
        assignments = ', '.join(f'{key} = EXCLUDED.{key}' for key in columns if key != 'id')
        query = f"INSERT INTO planning_history ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))}) ON CONFLICT (id) DO UPDATE SET {assignments}"
        with self.connect() as conn:
            conn.execute(query, [values[column] for column in columns])

    def get(self, job_id: str) -> PlanningJob | None:
        with self.connect() as conn:
            row = conn.execute('SELECT job_json FROM planning_history WHERE id = %s', (job_id,)).fetchone()
        return JOB_CODEC.validate_python(row['job_json']) if row else None

    def get_request(self, job_id: str) -> PlanningRequest:
        with self.connect() as conn:
            row = conn.execute('SELECT request_json FROM planning_history WHERE id = %s', (job_id,)).fetchone()
        if row is None:
            raise ValueError('Не найдены исходные данные сохранённого задания')
        return REQUEST_CODEC.validate_python(row['request_json'])

    def statistics(self, limit: int = 25, offset: int = 0, status: str | None = None):
        where, args = (' WHERE status = %s', [status]) if status else ('', [])
        with self.connect() as conn:
            summary = conn.execute('''SELECT count(*) AS total,
                count(*) FILTER (WHERE status = 'completed') AS completed,
                count(*) FILTER (WHERE status = 'failed') AS failed,
                avg(calculation_seconds) AS average_calculation_seconds,
                max(peak_rss_bytes) AS maximum_peak_rss_bytes
                FROM planning_history''' + where, args).fetchone()
            rows = conn.execute('''SELECT id, status, product_card_id, quantity, created_at, started_at,
                finished_at, calculation_seconds, memory_start_bytes, peak_rss_bytes, memory_growth_bytes,
                department_count, operation_count, plan_makespan_seconds, plan_work_seconds, selected_department, memory_scope
                FROM planning_history''' + where + ' ORDER BY finished_at DESC, id LIMIT %s OFFSET %s', [*args, limit, offset]).fetchall()
        for row in rows:
            row['id'] = str(row['id'])
            for key in ('created_at', 'started_at', 'finished_at'):
                row[key] = row[key].isoformat() if row[key] else None
        return {'summary': summary, 'items': rows, 'limit': limit, 'offset': offset}
