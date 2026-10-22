"""Integration tests for employee assignment by CP-SAT."""

from collections import defaultdict
from dataclasses import replace
import math
import unittest

from planner.application import ProductionPlanningService
from planner.infrastructure.cp_sat_planner import CpSatProductionPlanner
from planner.infrastructure.test_data import generate_test_data


class CpSatProductionPlannerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = generate_test_data()
        # Keep the integration scenario inside one shift independently of
        # demonstration data, which can describe a multi-day process.
        request = cls.data.request
        process = request.task.tech_process
        process = replace(process, stages=tuple(
            replace(stage, groups=tuple(
                replace(group, operations=tuple(
                    replace(operation, norm_sec=min(operation.norm_sec, 300))
                    for operation in group.operations
                )) for group in stage.groups
            )) for stage in process.stages
        ))
        cls.request = replace(request, task=replace(request.task, tech_process=process))
        cls.plan = ProductionPlanningService(
            CpSatProductionPlanner(max_time_sec=20)
        ).create_plan(cls.request)

    def test_assigns_every_operation_once(self) -> None:
        expected_count = (
            len(self.request.task.tech_process.operations) * self.request.task.count
        )
        self.assertEqual(expected_count, len(self.plan.operations))
        keys = {
            (operation.unit_number, operation.operation_id)
            for operation in self.plan.operations
        }
        self.assertEqual(expected_count, len(keys))

    def test_rejects_process_that_cannot_fit_in_a_day(self) -> None:
        process = self.request.task.tech_process
        process = replace(process, stages=tuple(
            replace(stage, groups=tuple(
                replace(group, operations=tuple(
                    replace(operation, norm_sec=5000) for operation in group.operations
                )) for group in stage.groups
            )) for stage in process.stages
        ))
        request = replace(self.request, task=replace(self.request.task, tech_process=process))
        with self.assertRaisesRegex(ValueError, 'План не помещается в рабочий день'):
            CpSatProductionPlanner().plan(request)

    def test_unknown_explains_time_limit(self) -> None:
        from unittest.mock import patch
        from ortools.sat.python import cp_model

        with patch.object(cp_model.CpSolver, 'solve', return_value=cp_model.UNKNOWN):
            with self.assertRaisesRegex(RuntimeError, 'За отведённое время'):
                CpSatProductionPlanner().plan(self.request)

    def test_assignments_use_known_departments_without_overlaps(self) -> None:
        self.assertLessEqual(
            {operation.department_id for operation in self.plan.operations},
            {department.id for department in self.request.departments},
        )
        for department in self.request.departments:
            operations = sorted(
                (operation for operation in self.plan.operations if operation.department_id == department.id),
                key=lambda operation: operation.starts_at,
            )
            for previous, current in zip(operations, operations[1:]):
                self.assertLessEqual(previous.ends_at, current.starts_at)

    def test_employee_is_qualified_and_efficiency_changes_duration(self) -> None:
        employees = {employee.id: employee for employee in self.request.employees}
        efficiencies = {
            (item.employee_id, item.equipment_type_id): item.percent
            for item in self.request.efficiencies
        }
        process_operations = {
            operation.id: operation
            for operation in self.request.task.tech_process.operations
        }
        for planned in self.plan.operations:
            employee = employees[planned.employee_id]
            operation = process_operations[planned.operation_id]
            self.assertTrue(employee.can_use(operation.equipment_type.id))
            self.assertEqual(
                efficiencies[(employee.id, operation.equipment_type.id)],
                planned.efficiency_percent,
            )
            self.assertEqual(
                math.ceil(planned.norm_sec * 100 / planned.efficiency_percent),
                planned.duration_sec,
            )

    def test_operations_stay_inside_employee_shift(self) -> None:
        schedules = {
            schedule.employee_id: schedule
            for schedule in self.request.work_schedules
        }
        for operation in self.plan.operations:
            schedule = schedules[operation.employee_id]
            self.assertTrue(schedule.is_work_hours(operation.starts_at))
            self.assertLessEqual(operation.ends_at.time(), schedule.work_end)

    def test_one_employee_never_has_overlapping_operations(self) -> None:
        by_employee = defaultdict(list)
        for operation in self.plan.operations:
            by_employee[operation.employee_id].append(operation)
        for employee_operations in by_employee.values():
            employee_operations.sort(key=lambda operation: operation.starts_at)
            for previous, current in zip(
                employee_operations, employee_operations[1:]
            ):
                self.assertLessEqual(previous.ends_at, current.starts_at)

    def test_stages_are_executed_in_order(self) -> None:
        by_stage = defaultdict(list)
        for operation in self.plan.operations:
            by_stage[operation.stage].append(operation)
        for previous_stage, current_stage in zip(range(1, 6), range(2, 7)):
            previous_end = max(
                operation.ends_at for operation in by_stage[previous_stage]
            )
            current_start = min(
                operation.starts_at for operation in by_stage[current_stage]
            )
            self.assertLessEqual(previous_end, current_start)


if __name__ == "__main__":
    unittest.main()
