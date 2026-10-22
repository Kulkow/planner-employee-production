"""Separate Redis queue consumer; CPU-intensive planning never runs in ASGI."""

from datetime import datetime, timezone
import logging
import signal
import socket
from uuid import uuid4

from redis import Redis
from redis.exceptions import RedisError

from planner.application import ProductionPlanningService
from planner.application.jobs import PlanningJobService
from planner.domain.jobs import JobStatus
from planner.infrastructure.cp_sat_planner import CpSatProductionPlanner
from planner.infrastructure.redis_jobs import RedisPlanningJobs, redis_url

logger = logging.getLogger(__name__)


def process_message(store: RedisPlanningJobs, service: PlanningJobService, message) -> None:
    message_id, fields = message
    job = store.get(fields['job_id'])
    if job is None:
        raise ValueError('Queue entry has no planning job')
    if job.status == JobStatus.PENDING:
        try:
            request = store.get_request(job.id)
        except ValueError as error:
            store.save(job.start(datetime.now(timezone.utc)).fail(str(error), datetime.now(timezone.utc)))
        else:
            service.execute(job, request)
    elif job.status == JobStatus.RUNNING:
        store.save(job.fail('Расчёт прерван при остановке worker. Создайте новое задание.', datetime.now(timezone.utc)))
    store.acknowledge(message_id)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    client = Redis.from_url(redis_url(), decode_responses=True, socket_connect_timeout=5, socket_timeout=10)
    store = RedisPlanningJobs(client)
    service = PlanningJobService(ProductionPlanningService(CpSatProductionPlanner()), store)
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
                    process_message(store, service, message)
            except RedisError:
                logger.exception('Redis unavailable; worker will restart')
                raise
            except Exception:
                logger.exception('Failed processing queue entry; delivery remains pending')
    finally:
        client.close()


if __name__ == '__main__':
    main()
