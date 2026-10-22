"""Planning job aggregate and lifecycle."""

from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import Enum

from planner.domain.planning import ProductionPlan
from planner.domain.planning.entities import DepartmentPlanningResult
from planner.domain.production import ProductionTask


class JobStatus(str, Enum):
    PENDING = 'pending'
    RUNNING = 'running'
    COMPLETED = 'completed'
    FAILED = 'failed'


@dataclass(frozen=True)
class PlanningJob:
    id: str
    task: ProductionTask
    planning_day: date
    created_at: datetime
    status: JobStatus = JobStatus.PENDING
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: ProductionPlan | None = None
    error: str | None = None
    department_results: tuple[DepartmentPlanningResult, ...] = ()

    def record_department(self, result: DepartmentPlanningResult) -> 'PlanningJob':
        if self.status != JobStatus.RUNNING:
            raise ValueError('Only a running job can record a scenario')
        if any(item.department_id == result.department_id for item in self.department_results):
            raise ValueError('Department scenario has already been calculated')
        if result.plan and (result.plan.product_card_id, result.plan.count) != (self.task.product_card_id, self.task.count):
            raise ValueError('Scenario must match the requested product and quantity')
        return replace(self, department_results=(*self.department_results, result))

    @property
    def duration_sec(self) -> float | None:
        if self.started_at is None or self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds()

    def start(self, now: datetime) -> 'PlanningJob':
        if self.status != JobStatus.PENDING or now < self.created_at:
            raise ValueError('Only a pending job can start, after its creation')
        return replace(self, status=JobStatus.RUNNING, started_at=now)

    def complete(self, result: ProductionPlan, now: datetime) -> 'PlanningJob':
        self._validate_finish(now)
        if (result.product_card_id, result.count) != (self.task.product_card_id, self.task.count):
            raise ValueError('Plan must match the requested product and quantity')
        return replace(self, status=JobStatus.COMPLETED, finished_at=now, result=result)

    def fail(self, error: str, now: datetime) -> 'PlanningJob':
        self._validate_finish(now)
        if not error.strip():
            raise ValueError('Failure reason is required')
        return replace(self, status=JobStatus.FAILED, finished_at=now, error=error)

    def _validate_finish(self, now: datetime) -> None:
        if self.status != JobStatus.RUNNING or self.started_at is None or now < self.started_at:
            raise ValueError('Only a running job can finish, after its start')
