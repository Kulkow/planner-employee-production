"""Separate Redis queue consumer; CPU-intensive planning never runs in ASGI."""

from datetime import datetime, timezone
from dataclasses import replace
import logging
import signal
import socket
import os
from uuid import uuid4

from redis import Redis
from redis.exceptions import RedisError

from planner.application import ProductionPlanningService
from planner.application.jobs import PlanningJobArchive, PlanningJobService
from planner.domain.jobs import JobStatus
from planner.infrastructure.cp_sat_planner import CpSatProductionPlanner
from planner.infrastructure.redis_jobs import RedisPlanningJobs, redis_url
from planner.infrastructure.planning_metrics import ProcessMemorySampler
from planner.infrastructure.postgres_jobs import PostgresPlanningArchive
from planner.infrastructure.parallel_departments import ParallelDepartmentRunner

logger = logging.getLogger(__name__)


def process_message(store: RedisPlanningJobs, service: PlanningJobService, message, archive: PlanningJobArchive | None = None) -> None:
    message_id, fields = message
    job = store.get(fields['job_id'])
    if job is None:
        raise ValueError('Queue entry has no planning job')
    if job.status == JobStatus.PENDING:
        try:
            request = store.get_request(job.id)
        except ValueError as error:
            job = job.start(datetime.now(timezone.utc)).fail(str(error), datetime.now(timezone.utc))
            store.save(job)
        else:
            with ProcessMemorySampler(include_children=True) as sampler:
                job = service.execute(job, request)
            job = replace(job, metrics=sampler.metrics)
            store.save(job)
    elif job.status == JobStatus.RUNNING:
        job = job.fail('Расчёт прерван при остановке worker. Создайте новое задание.', datetime.now(timezone.utc))
        store.save(job)
    if archive is not None:
        # Never acknowledge a delivery until the full result is durably stored.
        archive.save(job, store.get_request(job.id))
    store.acknowledge(message_id)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    client = Redis.from_url(redis_url(), decode_responses=True, socket_connect_timeout=5, socket_timeout=10)
    store = RedisPlanningJobs(client)
    archive = PostgresPlanningArchive.from_env()
    if archive is not None:
        archive.initialize()
    department_processes = int(os.environ.get('DEPARTMENT_PROCESSES', '4'))
    service = PlanningJobService(ProductionPlanningService(CpSatProductionPlanner()), store,
                                 ParallelDepartmentRunner(max_workers=department_processes))
    consumer = f'{socket.gethostname()}-{uuid4()}'
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        store.ensure_group()
        while not stopping:
            try:
                message = store.receive(consumer)
                if message:
                    process_message(store, service, message, archive)
            except RedisError:
                logger.exception('Redis unavailable; worker will restart')
                raise
            except Exception:
                logger.exception('Failed processing queue entry; delivery remains pending')
    finally:
        client.close()


if __name__ == '__main__':
    main()
