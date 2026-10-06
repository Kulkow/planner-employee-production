"""Tests for domain rules and the deterministic data generator."""

from collections import Counter
from datetime import datetime
import unittest

from planner.infrastructure.test_data import generate_test_data


class TestDataGeneratorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.data = generate_test_data()
        self.request = self.data.request

    def test_generates_four_departments_with_ten_employees_each(self) -> None:
        self.assertEqual(4, len(self.request.departments))
        employee_counts = Counter(
            employee.department_id for employee in self.request.employees
        )
        self.assertEqual(40, len(self.request.employees))
        self.assertEqual({10}, set(employee_counts.values()))

    def test_generates_efficiency_between_60_and_90_percent(self) -> None:
        self.assertEqual(40, len(self.request.efficiencies))
        self.assertTrue(
            all(60 <= item.percent <= 90 for item in self.request.efficiencies)
        )
        qualification_keys = {
            (employee.id, equipment.equipment_type_id)
            for employee in self.request.employees
            for equipment in employee.equipment
        }
        efficiency_keys = {
            (item.employee_id, item.equipment_type_id)
            for item in self.request.efficiencies
        }
        self.assertEqual(qualification_keys, efficiency_keys)

    def test_generates_six_stage_technological_process(self) -> None:
        stages = self.request.task.tech_process.stages
        self.assertEqual(6, len(stages))
        for stage in stages:
            self.assertGreaterEqual(len(stage.groups), 2)
            self.assertLessEqual(len(stage.groups), 4)
            for group in stage.groups:
                self.assertGreaterEqual(len(group.operations), 2)
                self.assertLessEqual(len(group.operations), 5)
                for operation in group.operations:
                    self.assertGreaterEqual(operation.norm_sec, 5)
                    self.assertLessEqual(operation.norm_sec, 30)

    def test_every_operation_has_qualified_employees(self) -> None:
        for operation in self.request.task.tech_process.operations:
            qualified = [
                employee
                for employee in self.request.employees
                if employee.can_use(operation.equipment_type.id)
            ]
            self.assertEqual(10, len(qualified))

    def test_work_schedule_is_five_by_two_from_0830_to_1630(self) -> None:
        schedule = self.request.work_schedules[0]
        monday = datetime(2026, 10, 5, 8, 30)
        saturday = datetime(2026, 10, 10, 9, 0)
        self.assertTrue(schedule.is_work_hours(monday))
        self.assertTrue(schedule.is_work_hours(monday.replace(hour=16, minute=29)))
        self.assertFalse(schedule.is_work_hours(monday.replace(hour=16, minute=30)))
        self.assertFalse(schedule.is_work_hours(saturday))
        self.assertEqual(8 * 60 * 60, schedule.shift_duration_sec)

    def test_seed_makes_data_reproducible(self) -> None:
        duplicate = generate_test_data()
        self.assertEqual(self.request, duplicate.request)


if __name__ == "__main__":
    unittest.main()
