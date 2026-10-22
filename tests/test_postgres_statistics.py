"""Real PostgreSQL persistence, metrics, worker acknowledgement and history API."""

from dataclasses import replace
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import psycopg
from fastapi.testclient import TestClient
from redis import Redis

from planner.application import ProductionPlanningService
from planner.application.jobs import PlanningJobService
from planner.domain.jobs import PlanningMetrics
from planner.infrastructure.cp_sat_planner import CpSatProductionPlanner
from planner.infrastructure.planning_metrics import ProcessMemorySampler
from planner.infrastructure.postgres_jobs import PostgresPlanningArchive
from planner.infrastructure.redis_jobs import RedisPlanningJobs
from planner.migrate_history import migrate
from planner.web import app
from planner.worker import process_message
from test_department_planning import request_for_test


class PlanningMetricsTest(unittest.TestCase):
    def test_tree_sampler_counts_children(self):
        sampler = ProcessMemorySampler(include_children=True)
        sampler._process = Mock()
        sampler._process.memory_info.return_value = SimpleNamespace(rss=100)
        child = Mock()
        child.memory_info.return_value = SimpleNamespace(rss=300)
        sampler._process.children.return_value = [child]
        self.assertEqual(sampler._read_rss(), 400)

    def test_sampler_measures_this_run_not_process_lifetime_high_water_mark(self):
        sampler = ProcessMemorySampler(interval=60)
        sampler._process = Mock()
        sampler._process.memory_info.side_effect = [SimpleNamespace(rss=value) for value in (100, 500, 200)]
        with sampler:
            sampler._sample()
        self.assertEqual(sampler.metrics.memory_start_bytes, 100)
        self.assertEqual(sampler.metrics.peak_rss_bytes, 500)
        self.assertGreaterEqual(sampler.metrics.elapsed_seconds, 0)
        self.assertFalse(sampler._thread.is_alive())
        with self.assertRaises(ValueError):
            PlanningMetrics(1, 200, 100)


@unittest.skipUnless(os.environ.get('DATABASE_URL') and os.environ.get('REDIS_URL'), 'Set database and Redis URLs')
class PostgresStatisticsTest(unittest.TestCase):
    def setUp(self):
        self.redis = Redis.from_url(os.environ['REDIS_URL'], decode_responses=True)
        self.prefix = f'test:archive:{uuid4()}'
        self.store = RedisPlanningJobs(self.redis, self.prefix)
        self.archive = PostgresPlanningArchive(os.environ['DATABASE_URL'])
        self.archive.initialize()
        self.client = TestClient(app)
        self.client.__enter__()
        app.state.jobs = self.store
        app.state.archive = self.archive
        self.store.ensure_group()
        self.ids = []

    def tearDown(self):
        self.client.__exit__(None, None, None)
        if self.ids:
            with self.archive.connect() as conn:
                conn.execute('DELETE FROM planning_history WHERE id = ANY(%s::uuid[])', (self.ids,))
        keys = list(self.redis.scan_iter(f'{self.prefix}:*'))
        if keys:
            self.redis.delete(*keys)
        self.redis.close()

    def submit(self):
        with patch('planner.web.generate_test_data', return_value=SimpleNamespace(request=request_for_test())):
            response = self.client.post('/api/jobs', json={'count': 2, 'horizon_days': 1})
        self.assertEqual(response.status_code, 202)
        data = response.json()
        self.ids.append(data['job']['id'])
        return data

    def service(self):
        return PlanningJobService(ProductionPlanningService(CpSatProductionPlanner(max_time_sec=1)), self.store)

    def test_archive_round_trip_upsert_metrics_statistics_and_read_without_redis(self):
        data = self.submit()
        baseline = self.archive.statistics()['summary']['total']
        process_message(self.store, self.service(), self.store.receive('worker'), self.archive)
        job = self.archive.get(data['job']['id'])
        self.assertEqual(job, self.store.get(job.id))
        self.assertEqual(len(job.department_results), 2)
        self.assertIsNotNone(job.metrics)
        self.assertGreater(job.metrics.peak_rss_bytes, 0)
        self.assertGreaterEqual(job.metrics.peak_rss_bytes, job.metrics.memory_start_bytes)
        self.archive.save(job, self.store.get_request(job.id))
        self.assertEqual(self.archive.statistics()['summary']['total'], baseline + 1)
        statistics = self.client.get('/api/statistics').json()
        item = next(row for row in statistics['items'] if row['id'] == job.id)
        self.assertEqual(item['operation_count'], 4)
        self.assertEqual(item['department_count'], 2)
        self.assertEqual(item['peak_rss_bytes'], job.metrics.peak_rss_bytes)
        self.assertEqual(item['memory_scope'], 'process_tree')
        self.assertGreater(item['calculation_seconds'], 0)
        # Both inputs and full comparison remain accessible after Redis removal.
        self.redis.delete(self.store.job_key(job.id), f'{self.prefix}:request:{job.id}')
        with patch.object(self.store, 'get', side_effect=__import__('redis').exceptions.ConnectionError()):
            restored = self.client.get(data['resultUrl'])
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(restored.json()['completedDepartments'], 2)
        self.assertEqual(len(restored.json()['departmentComparison'][0]['operations']), 4)
        page = self.client.get('/statistics')
        self.assertEqual(page.status_code, 200)
        self.assertIn('Пик RSS', page.text)

    def test_database_failure_does_not_ack_and_retry_does_not_recalculate(self):
        data = self.submit()
        message = self.store.receive('worker')
        broken = Mock()
        broken.save.side_effect = psycopg.OperationalError('database unavailable')
        with self.assertRaises(psycopg.OperationalError):
            process_message(self.store, self.service(), message, broken)
        self.assertEqual(self.redis.xpending(self.store.stream, self.store.group)['pending'], 1)
        retry_service = Mock()
        process_message(self.store, retry_service, self.store.receive('retry', idle_ms=0), self.archive)
        retry_service.execute.assert_not_called()
        self.assertIsNotNone(self.archive.get(data['job']['id']).metrics)
        self.assertEqual(self.redis.xpending(self.store.stream, self.store.group)['pending'], 0)

    def test_failed_and_historical_jobs_keep_null_memory_and_import_is_idempotent(self):
        data = self.submit()
        service = Mock()
        service.create_plan.side_effect = ValueError('Нет доступной смены')
        job = PlanningJobService(service, self.store).execute(self.store.get(data['job']['id']), self.store.get_request(data['job']['id']))
        self.assertEqual(job.status.value, 'failed')
        self.assertEqual(migrate(self.store, self.archive), 1)
        self.assertEqual(migrate(self.store, self.archive), 0)
        statistics = self.client.get('/api/statistics?status=failed&limit=100').json()
        item = next(row for row in statistics['items'] if row['id'] == job.id)
        self.assertIsNone(item['peak_rss_bytes'])
        self.assertIsNone(item['memory_growth_bytes'])
        self.assertIsNone(item['plan_makespan_seconds'])
        self.assertEqual(self.archive.get(job.id).error, job.error)
        self.assertEqual(self.client.get('/api/statistics?limit=0').status_code, 422)
        self.assertEqual(self.client.get('/api/statistics?status=running').status_code, 422)
        with patch.object(self.archive, 'statistics', side_effect=psycopg.OperationalError('offline')):
            self.assertEqual(self.client.get('/api/statistics').status_code, 503)
