"""Import completed Redis jobs into PostgreSQL without inventing memory metrics."""

from redis import Redis

from planner.domain.jobs import JobStatus
from planner.infrastructure.postgres_jobs import PostgresPlanningArchive
from planner.infrastructure.redis_jobs import RedisPlanningJobs, redis_url


def migrate(store, archive) -> int:
    count = 0
    for job_id, _ in store.client.zscan_iter(f'{store.prefix}:jobs'):
        job = store.get(job_id)
        if job and job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
            # Preserve measurements already archived by a newer worker.
            if archive.get(job.id) is None:
                archive.save(job, store.get_request(job.id))
                count += 1
    return count


def main():
    archive = PostgresPlanningArchive.from_env()
    if archive is None:
        raise SystemExit('Set DATABASE_URL to import planning history')
    archive.initialize()
    with Redis.from_url(redis_url(), decode_responses=True) as client:
        print(f'Imported {migrate(RedisPlanningJobs(client), archive)} terminal jobs')


if __name__ == '__main__':
    main()
