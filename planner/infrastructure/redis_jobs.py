"""Redis JSON repository, durable stream queue and Pub/Sub notifications."""

import os

from pydantic import TypeAdapter
from redis import Redis
from redis.exceptions import ResponseError

from planner.application.planning import PlanningRequest
from planner.domain.jobs import PlanningJob

JOB_CODEC = TypeAdapter(PlanningJob)
REQUEST_CODEC = TypeAdapter(PlanningRequest)


def redis_url() -> str:
    return os.environ.get('REDIS_URL', 'redis://localhost:6379/0')


class RedisPlanningJobs:
    def __init__(self, client: Redis, prefix: str = 'planner'):
        self.client = client
        self.prefix = prefix
        self.stream = f'{prefix}:queue'
        self.group = 'planners'
        self._claim_cursor = '0-0'

    def job_key(self, job_id: str) -> str:
        return f'{self.prefix}:job:{job_id}'

    def channel(self, job_id: str) -> str:
        return f'{self.prefix}:events:{job_id}'

    def save(self, job: PlanningJob) -> None:
        with self.client.pipeline() as pipe:
            pipe.set(self.job_key(job.id), JOB_CODEC.dump_json(job))
            pipe.zadd(f'{self.prefix}:jobs', {job.id: job.created_at.timestamp()})
            pipe.publish(self.channel(job.id), job.status.value)
            pipe.execute()

    def enqueue(self, job: PlanningJob, request: PlanningRequest) -> None:
        # Save the exact resource snapshot and enqueue atomically.
        with self.client.pipeline() as pipe:
            pipe.set(self.job_key(job.id), JOB_CODEC.dump_json(job))
            pipe.set(f'{self.prefix}:request:{job.id}', REQUEST_CODEC.dump_json(request))
            pipe.zadd(f'{self.prefix}:jobs', {job.id: job.created_at.timestamp()})
            pipe.xadd(self.stream, {'job_id': job.id})
            pipe.publish(self.channel(job.id), job.status.value)
            pipe.execute()

    def get(self, job_id: str) -> PlanningJob | None:
        raw = self.client.get(self.job_key(job_id))
        return JOB_CODEC.validate_json(raw) if raw else None

    def get_request(self, job_id: str) -> PlanningRequest:
        raw = self.client.get(f'{self.prefix}:request:{job_id}')
        if raw is None:
            raise ValueError('Не найдены исходные данные задания')
        return REQUEST_CODEC.validate_json(raw)

    def list(self, limit: int = 100) -> tuple[PlanningJob, ...]:
        ids = self.client.zrevrange(f'{self.prefix}:jobs', 0, limit - 1)
        if not ids:
            return ()
        values = self.client.mget([self.job_key(job_id) for job_id in ids])
        return tuple(JOB_CODEC.validate_json(raw) for raw in values if raw)

    def ensure_group(self) -> None:
        try:
            self.client.xgroup_create(self.stream, self.group, id='0', mkstream=True)
        except ResponseError as error:
            if 'BUSYGROUP' not in str(error):
                raise

    def receive(self, consumer: str, idle_ms: int = 300_000):
        # Reclaim a delivery left by an interrupted worker after five minutes.
        claimed = self.client.xautoclaim(
            self.stream, self.group, consumer, idle_ms, start_id=self._claim_cursor, count=1,
        )
        self._claim_cursor = claimed[0]
        if claimed[1]:
            return claimed[1][0]
        messages = self.client.xreadgroup(self.group, consumer, {self.stream: '>'}, count=1, block=1000)
        return messages[0][1][0] if messages else None

    def acknowledge(self, message_id: str) -> None:
        with self.client.pipeline() as pipe:
            pipe.xack(self.stream, self.group, message_id)
            pipe.xdel(self.stream, message_id)
            pipe.execute()
