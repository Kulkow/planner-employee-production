"""Production planning use case and its infrastructure port."""

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from planner.domain.employees import Department, Employee, EmployeeEfficiency
from planner.domain.planning import ProductionPlan
from planner.domain.production import ProductionTask
from planner.domain.schedules import WorkSchedule


@dataclass(frozen=True)
class PlanningRequest:
    task: ProductionTask
    departments: tuple[Department, ...]
    employees: tuple[Employee, ...]
    efficiencies: tuple[EmployeeEfficiency, ...]
    work_schedules: tuple[WorkSchedule, ...]
    planning_day: date


class ProductionPlanner(Protocol):
    def plan(self, request: PlanningRequest) -> ProductionPlan:
        """Build an employee assignment and operation schedule."""


class ProductionPlanningService:
    """Validates an input snapshot and delegates optimization to a planner."""

    def __init__(self, planner: ProductionPlanner) -> None:
        self._planner = planner

    def create_plan(self, request: PlanningRequest) -> ProductionPlan:
        employee_ids = {employee.id for employee in request.employees}
        department_ids = {department.id for department in request.departments}
        employee_equipment_keys = {
            (employee.id, equipment.equipment_type_id)
            for employee in request.employees
            for equipment in employee.equipment
        }
        efficiency_keys = {
            (efficiency.employee_id, efficiency.equipment_type_id)
            for efficiency in request.efficiencies
        }
        schedule_employee_ids = {
            schedule.employee_id for schedule in request.work_schedules
        }

        if len(employee_ids) != len(request.employees):
            raise ValueError("Employee ids must be unique")
        if any(
            employee.department_id not in department_ids
            for employee in request.employees
        ):
            raise ValueError("Every employee must belong to a known department")
        if len(efficiency_keys) != len(request.efficiencies):
            raise ValueError("Employee efficiency keys must be unique")
        if employee_equipment_keys != efficiency_keys:
            raise ValueError(
                "Every employee equipment qualification must have one efficiency value"
            )
        if employee_ids != schedule_employee_ids:
            raise ValueError("Every employee must have one work schedule")

        return self._planner.plan(request)
