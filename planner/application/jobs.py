"""Planning job use case and repository port."""

from datetime import datetime, timezone
from dataclasses import replace
from typing import Iterable, Protocol
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


class PlanningJobArchive(Protocol):
    def save(self, job: PlanningJob, request: PlanningRequest) -> None: ...
    def get(self, job_id: str) -> PlanningJob | None: ...
    def get_request(self, job_id: str) -> PlanningRequest: ...


class DepartmentRunner(Protocol):
    def run(self, requests: tuple[PlanningRequest, ...]) -> Iterable[DepartmentPlanningResult]: ...


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
    def __init__(self, planning: ProductionPlanningService, repository: PlanningJobRepository,
                 department_runner: DepartmentRunner | None = None):
        self._planning = planning
        self._repository = repository
        self._department_runner = department_runner

    def generate(self, request: PlanningRequest) -> PlanningJob:
        job = new_job(request)
        self._repository.save(job)
        return self.execute(job, request)

    def execute(self, job: PlanningJob, request: PlanningRequest) -> PlanningJob:
        job = job.start(datetime.now(timezone.utc))
        self._repository.save(job)
        try:
            if request.compare_departments:
                scenarios = []
                for department in request.departments:
                    members = tuple(employee for employee in request.employees if employee.department_id == department.id)
                    member_ids = {employee.id for employee in members}
                    scenario = replace(
                        request, departments=(department,), employees=members,
                        efficiencies=tuple(item for item in request.efficiencies if item.employee_id in member_ids),
                        work_schedules=tuple(item for item in request.work_schedules if item.employee_id in member_ids),
                        employee_workloads=tuple(item for item in request.employee_workloads if item.employee_id in member_ids),
                        compare_departments=False,
                    )
                    scenarios.append(scenario)
                if self._department_runner is not None:
                    job = job.start_departments(tuple(item.departments[0].id for item in scenarios))
                    self._repository.save(job)
                    outcomes = self._department_runner.run(tuple(scenarios))
                else:
                    outcomes = (self._calculate_department(scenario) for scenario in scenarios)
                expected = {department.id for department in request.departments}
                for outcome in outcomes:
                    if outcome.department_id not in expected:
                        raise ValueError('Unexpected department result')
                    job = job.record_department(outcome)
                    self._repository.save(job)
                if {item.department_id for item in job.department_results} != expected:
                    raise ValueError('Some departments did not return a result')
                successful = [item.plan for item in job.department_results if item.plan is not None]
                if not successful:
                    raise ValueError('Ни одна бригада не выполнила задание в заданных условиях. Причины указаны для каждой бригады.')
                # Compare actual completion dates from the same planning origin.
                result = min(successful, key=lambda plan: (max(operation.ends_at for operation in plan.operations), plan.operations[0].department_id))
            else:
                result = self._planning.create_plan(request)
            job = job.complete(result, datetime.now(timezone.utc))
        except Exception as error:
            job = job.fail(str(error) or type(error).__name__, datetime.now(timezone.utc))
        self._repository.save(job)
        return job

    def _calculate_department(self, request: PlanningRequest) -> DepartmentPlanningResult:
        department = request.departments[0]
        started = datetime.now(timezone.utc)
        plan, error = None, None
        try:
            plan = self._planning.create_plan(request)
        except Exception as failure:
            error = str(failure) or type(failure).__name__
        return DepartmentPlanningResult(department.id, department.name, started, datetime.now(timezone.utc), plan, error)
