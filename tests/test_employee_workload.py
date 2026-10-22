"""Daily workload invariants, test data and solver capacity constraints."""

from dataclasses import replace
from datetime import date
import unittest
from unittest.mock import Mock

from planner.application import ProductionPlanningService
from planner.application.jobs import PlanningJobService
from planner.domain.employees import EmployeeWorkload
from planner.infrastructure.cp_sat_planner import CpSatProductionPlanner
from planner.infrastructure.planning_jobs import InMemoryPlanningJobRepository
from planner.infrastructure.test_data import generate_test_data
from planner.infrastructure.redis_jobs import REQUEST_CODEC
from test_department_planning import request_for_test


class EmployeeWorkloadTest(unittest.TestCase):
    def test_validates_seconds_and_balance(self):
        day = date(2026, 10, 5)
        for values in ((-1, 0, -1), (100, -1, 101), (100, 101, -1), (100, 50, 51), (100, True, 99)):
            with self.assertRaises(ValueError):
                EmployeeWorkload(1, day, *values)
        self.assertEqual(EmployeeWorkload(1, day, 100, 100, 0).available_seconds, 0)
        self.assertEqual(EmployeeWorkload(1, day, 100, 0, 100).available_seconds, 100)

    def test_generator_creates_reproducible_random_load_for_all_departments(self):
        request = generate_test_data().request
        self.assertEqual(len(request.employee_workloads), len(request.employees))
        self.assertEqual(request.employee_workloads, generate_test_data().request.employee_workloads)
        loads = {item.employee_id: item for item in request.employee_workloads}
        signatures = []
        for department in request.departments:
            members = [loads[e.id] for e in request.employees if e.department_id == department.id]
            self.assertEqual(len(members), 10)
            signatures.append(tuple(item.allocated_seconds for item in members))
            for item in members:
                self.assertEqual(item.date, request.planning_day)
                self.assertEqual(item.planned_seconds, 8 * 3600)
                self.assertTrue(0 <= item.allocated_seconds <= 3 * 3600)
                self.assertEqual(item.available_seconds, item.planned_seconds - item.allocated_seconds)
        self.assertEqual(len(set(signatures)), 4)
        self.assertEqual(REQUEST_CODEC.validate_json(REQUEST_CODEC.dump_json(request)), request)
        weekend = generate_test_data(planning_day=date(2026, 10, 10)).request
        self.assertTrue(all(item.planned_seconds == item.allocated_seconds == item.available_seconds == 0 for item in weekend.employee_workloads))

    def test_validates_employee_date_and_shift_capacity(self):
        request = request_for_test()
        service = ProductionPlanningService(Mock())
        load = EmployeeWorkload(1, request.planning_day, 28800, 0, 28800)
        for workloads in ((load, load), (replace(load, employee_id=99),),
                          (replace(load, planned_seconds=28801, available_seconds=28801),)):
            with self.assertRaises(ValueError):
                service.create_plan(replace(request, employee_workloads=workloads))

    def test_daily_limit_applies_to_sum_of_operations_and_carries_to_next_day(self):
        request = request_for_test()
        # Two 100-second operations; only 150 seconds remain on Monday.
        request = replace(request, task=replace(request.task, count=1),
                          employees=request.employees[:1], departments=request.departments[:1],
                          efficiencies=request.efficiencies[:1], work_schedules=request.work_schedules[:1],
                          horizon_days=2, employee_workloads=(EmployeeWorkload(1, request.planning_day, 28800, 28650, 150),))
        plan = ProductionPlanningService(CpSatProductionPlanner(max_time_sec=2)).create_plan(request)
        self.assertEqual(len(plan.operations), 2)
        self.assertEqual({o.starts_at.date() for o in plan.operations}, {date(2026, 10, 5), date(2026, 10, 6)})
        self.assertLessEqual(sum(o.duration_sec for o in plan.operations if o.starts_at.date() == request.planning_day), 150)

    def test_fully_allocated_employee_is_not_selected_on_that_date(self):
        request = request_for_test()
        request = replace(request, employee_workloads=(EmployeeWorkload(1, request.planning_day, 28800, 28800, 0),))
        plan = ProductionPlanningService(CpSatProductionPlanner(max_time_sec=2)).create_plan(request)
        self.assertNotIn(1, {operation.employee_id for operation in plan.operations})

    def test_comparison_filters_workload_to_own_department(self):
        request = request_for_test()
        request = replace(request, compare_departments=True, employee_workloads=tuple(
            EmployeeWorkload(employee.id, request.planning_day, 28800, 10800, 18000) for employee in request.employees))
        planning = Mock(wraps=ProductionPlanningService(CpSatProductionPlanner(max_time_sec=2)))
        job = PlanningJobService(planning, InMemoryPlanningJobRepository()).generate(request)
        self.assertEqual(job.status.value, 'completed')
        for call in planning.create_plan.call_args_list:
            isolated = call.args[0]
            self.assertEqual({item.employee_id for item in isolated.employee_workloads}, {e.id for e in isolated.employees})
