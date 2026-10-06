"""Integration tests for employee assignment by CP-SAT."""

from collections import defaultdict
import math
import unittest

from planner.application import ProductionPlanningService
from planner.infrastructure.cp_sat_planner import CpSatProductionPlanner
from planner.infrastructure.test_data import generate_test_data


class CpSatProductionPlannerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = generate_test_data()
        cls.request = cls.data.request
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

    def test_assignments_use_all_specialized_departments(self) -> None:
        self.assertEqual(
            {department.id for department in self.request.departments},
            {operation.department_id for operation in self.plan.operations},
        )

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
