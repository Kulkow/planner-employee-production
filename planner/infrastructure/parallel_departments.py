"""Bounded spawn pool: each process calculates one isolated department."""

from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from multiprocessing import get_context

from planner.application import PlanningRequest, ProductionPlanningService
from planner.domain.planning.entities import DepartmentPlanningResult
from planner.infrastructure.cp_sat_planner import CpSatProductionPlanner


def calculate_department(request: PlanningRequest, max_time_sec: float) -> DepartmentPlanningResult:
    department = request.departments[0]
    started = datetime.now(timezone.utc)
    plan, error = None, None
    try:
        plan = ProductionPlanningService(CpSatProductionPlanner(max_time_sec=max_time_sec)).create_plan(request)
    except Exception as failure:
        error = str(failure) or type(failure).__name__
    return DepartmentPlanningResult(department.id, department.name, started, datetime.now(timezone.utc), plan, error)


class ParallelDepartmentRunner:
    def __init__(self, max_workers: int = 4, max_time_sec: float = 20,
                 calculate=calculate_department):
        if type(max_workers) is not int or not 1 <= max_workers <= 16:
            raise ValueError('Department process count must be between 1 and 16')
        self.max_workers = max_workers
        self.max_time_sec = max_time_sec
        self._calculate = calculate

    def run(self, requests: tuple[PlanningRequest, ...]):
        if not requests:
            return
        # No Redis/PostgreSQL clients or live solver objects cross process boundaries.
        with ProcessPoolExecutor(max_workers=min(self.max_workers, len(requests)),
                                 mp_context=get_context('spawn')) as pool:
            submitted = datetime.now(timezone.utc)
            futures = {pool.submit(self._calculate, request, self.max_time_sec): request for request in requests}
            for future in as_completed(futures):
                request = futures[future]
                try:
                    yield future.result()
                except Exception as failure:
                    department = request.departments[0]
                    yield DepartmentPlanningResult(
                        department.id, department.name, submitted, datetime.now(timezone.utc),
                        error=f'Не удалось выполнить расчёт бригады: {str(failure) or type(failure).__name__}',
                    )
