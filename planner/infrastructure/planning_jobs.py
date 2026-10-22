"""Process-local planning job storage."""

from threading import Lock

from planner.domain.jobs import PlanningJob


class InMemoryPlanningJobRepository:
    def __init__(self):
        self._jobs: dict[str, PlanningJob] = {}
        self._lock = Lock()

    def save(self, job: PlanningJob) -> None:
        with self._lock:
            self._jobs[job.id] = job

    def get(self, job_id: str) -> PlanningJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> tuple[PlanningJob, ...]:
        with self._lock:
            return tuple(sorted(self._jobs.values(), key=lambda job: job.created_at, reverse=True))
