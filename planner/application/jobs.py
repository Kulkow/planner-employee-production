"""Planning job use case and repository port."""

from datetime import datetime, timezone
from dataclasses import replace
from typing import Protocol
from uuid import uuid4

from planner.application.planning import PlanningRequest, ProductionPlanningService
from planner.domain.jobs import PlanningJob
from planner.domain.planning.entities import DepartmentPlanningResult


class PlanningJobRepository(Protocol):
    def save(self, job: PlanningJob) -> None: ...
    def get(self, job_id: str) -> PlanningJob | None: ...
    def list(self) -> tuple[PlanningJob, ...]: ...


class PlanningJobQueue(Protocol):
    def enqueue(self, job: PlanningJob, request: PlanningRequest) -> None: ...


def new_job(request: PlanningRequest) -> PlanningJob:
    return PlanningJob(str(uuid4()), request.task, request.planning_day, datetime.now(timezone.utc))


class SubmitPlanningJob:
    def __init__(self, queue: PlanningJobQueue):
        self._queue = queue

    def submit(self, request: PlanningRequest) -> PlanningJob:
        job = new_job(request)
        self._queue.enqueue(job, request)
        return job


class PlanningJobService:
    def __init__(self, planning: ProductionPlanningService, repository: PlanningJobRepository):
        self._planning = planning
        self._repository = repository

    def generate(self, request: PlanningRequest) -> PlanningJob:
        job = new_job(request)
        self._repository.save(job)
        return self.execute(job, request)

    def execute(self, job: PlanningJob, request: PlanningRequest) -> PlanningJob:
        job = job.start(datetime.now(timezone.utc))
        self._repository.save(job)
        try:
            if request.compare_departments:
                for department in request.departments:
                    members = tuple(employee for employee in request.employees if employee.department_id == department.id)
                    member_ids = {employee.id for employee in members}
                    scenario = replace(
                        request, departments=(department,), employees=members,
                        efficiencies=tuple(item for item in request.efficiencies if item.employee_id in member_ids),
                        work_schedules=tuple(item for item in request.work_schedules if item.employee_id in member_ids),
                        compare_departments=False,
                    )
                    started = datetime.now(timezone.utc)
                    plan, error = None, None
                    try:
                        plan = self._planning.create_plan(scenario)
                    except Exception as failure:
                        error = str(failure) or type(failure).__name__
                    outcome = DepartmentPlanningResult(department.id, department.name, started, datetime.now(timezone.utc), plan, error)
                    job = job.record_department(outcome)
                    self._repository.save(job)
                successful = [item.plan for item in job.department_results if item.plan is not None]
                if not successful:
                    raise ValueError('Ни одна бригада не выполнила задание в заданных условиях. Причины указаны для каждой бригады.')
                # Compare actual completion dates from the same planning origin.
                result = min(successful, key=lambda plan: max(operation.ends_at for operation in plan.operations))
            else:
                result = self._planning.create_plan(request)
            job = job.complete(result, datetime.now(timezone.utc))
        except Exception as error:
            job = job.fail(str(error) or type(error).__name__, datetime.now(timezone.utc))
        self._repository.save(job)
        return job
