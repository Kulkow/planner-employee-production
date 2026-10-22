"""Real spawn processes, simultaneous execution and aggregate progress."""

from dataclasses import replace
from datetime import datetime, timezone
from functools import partial
from multiprocessing import get_context
import unittest

from planner.application import ProductionPlanningService
from planner.application.jobs import PlanningJobService
from planner.infrastructure.cp_sat_planner import CpSatProductionPlanner
from planner.infrastructure.parallel_departments import ParallelDepartmentRunner, calculate_department
from planner.infrastructure.planning_jobs import InMemoryPlanningJobRepository
from planner.presentation import plan_payload
from test_department_planning import request_for_test


def synchronized_calculation(request, max_time_sec, barrier):
    # A sequential implementation cannot pass this barrier before timeout.
    started = datetime.now(timezone.utc)
    barrier.wait(timeout=15)
    return replace(calculate_department(request, max_time_sec), started_at=started)


def failing_calculation(request, max_time_sec):
    if request.departments[0].id == 2:
        raise RuntimeError('Child calculation failed')
    return calculate_department(request, max_time_sec)


class RecordingRepository(InMemoryPlanningJobRepository):
    def __init__(self):
        super().__init__()
        self.history = []

    def save(self, job):
        super().save(job)
        self.history.append(job)


class ParallelDepartmentTest(unittest.TestCase):
    def service(self, runner, repository):
        return PlanningJobService(ProductionPlanningService(CpSatProductionPlanner(max_time_sec=1)), repository, runner)

    def test_spawn_processes_execute_simultaneously_without_losing_results(self):
        request = replace(request_for_test(), compare_departments=True)
        repository = RecordingRepository()
        with get_context('spawn').Manager() as manager:
            runner = ParallelDepartmentRunner(max_workers=2, max_time_sec=1,
                calculate=partial(synchronized_calculation, barrier=manager.Barrier(2)))
            job = self.service(runner, repository).generate(request)
        self.assertEqual(job.status.value, 'completed', job.error)
        self.assertEqual(len(job.department_results), 2)
        first, second = job.department_results
        self.assertLess(max(first.started_at, second.started_at), min(first.finished_at, second.finished_at))
        for result in job.department_results:
            self.assertEqual(len(result.plan.operations), 4)
            self.assertEqual({o.department_id for o in result.plan.operations}, {result.department_id})
        submitted = next(item for item in repository.history if len(item.running_department_ids) == 2)
        states = plan_payload(submitted, request)['departmentComparison']
        self.assertEqual([item['status'] for item in states], ['running', 'running'])
        partial_job = next(item for item in repository.history if len(item.department_results) == 1)
        self.assertEqual(len(partial_job.running_department_ids), 1)
        self.assertEqual(len(job.running_department_ids), 0)
        payload = plan_payload(job, request)
        self.assertEqual(sum(item['selected'] for item in payload['departmentComparison']), 1)

    def test_child_error_is_recorded_and_other_department_completes(self):
        request = replace(request_for_test(), compare_departments=True)
        runner = ParallelDepartmentRunner(max_workers=2, max_time_sec=1, calculate=failing_calculation)
        job = self.service(runner, RecordingRepository()).generate(request)
        self.assertEqual(job.status.value, 'completed', job.error)
        results = {item.department_id: item for item in job.department_results}
        self.assertIsNotNone(results[1].plan)
        self.assertIn('Child calculation failed', results[2].error)
        self.assertIsNone(results[2].plan)

    def test_concurrency_limit_is_validated(self):
        for value in (0, -1, 17, True):
            with self.assertRaises(ValueError):
                ParallelDepartmentRunner(max_workers=value)


class ConstructiveDepartmentTest(unittest.TestCase):
    def test_unknown_keeps_valid_complete_single_department_schedule(self):
        from collections import defaultdict
        from unittest.mock import patch
        from ortools.sat.python import cp_model
        from planner.infrastructure.test_data import generate_test_data
        original = generate_test_data().request
        department = original.departments[0]
        employees = tuple(e for e in original.employees if e.department_id == department.id)
        ids = {e.id for e in employees}
        request = replace(original, departments=(department,), employees=employees,
            efficiencies=tuple(e for e in original.efficiencies if e.employee_id in ids),
            work_schedules=tuple(s for s in original.work_schedules if s.employee_id in ids),
            employee_workloads=tuple(w for w in original.employee_workloads if w.employee_id in ids), horizon_days=14)
        with patch.object(cp_model.CpSolver, 'solve', return_value=cp_model.UNKNOWN):
            plan = ProductionPlanningService(CpSatProductionPlanner()).create_plan(request)
        self.assertEqual(plan.status, 'FEASIBLE')
        self.assertEqual(len(plan.operations), len(request.task.tech_process.operations))
        self.assertEqual({o.department_id for o in plan.operations}, {department.id})
        operations = sorted(plan.operations, key=lambda o: o.starts_at)
        for first, second in zip(operations, operations[1:]):
            self.assertLessEqual(first.ends_at, second.starts_at)
        schedules = {s.employee_id:s for s in request.work_schedules}
        daily = defaultdict(int)
        for operation in operations:
            self.assertTrue(schedules[operation.employee_id].is_work_hours(operation.starts_at))
            self.assertEqual(operation.starts_at.date(), operation.ends_at.date())
            self.assertLessEqual(operation.ends_at.time(), schedules[operation.employee_id].work_end)
            daily[operation.employee_id, operation.starts_at.date()] += operation.duration_sec
        for workload in request.employee_workloads:
            self.assertLessEqual(daily[workload.employee_id, workload.date], workload.available_seconds)
        by_operation = {o.operation_id:o for o in operations}
        for first_stage, second_stage in zip(request.task.tech_process.stages, request.task.tech_process.stages[1:]):
            self.assertLessEqual(max(by_operation[o.id].ends_at for o in first_stage.operations),
                                 min(by_operation[o.id].starts_at for o in second_stage.operations))
