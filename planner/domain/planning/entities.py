"""Result entities produced by the planning application service."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class DepartmentOption:
    department_id: int
    department_name: str
    min_duration_sec: int
    qualified_employee_count: int


@dataclass(frozen=True)
class ScheduledOperation:
    unit_number: int
    stage: int
    group_name: str
    operation_id: int
    employee_id: int
    employee_name: str
    department_id: int
    department_name: str
    equipment_code: str
    efficiency_percent: int
    norm_sec: int
    duration_sec: int
    starts_at: datetime
    ends_at: datetime
    department_options: tuple[DepartmentOption, ...] = ()


@dataclass(frozen=True)
class ProductionPlan:
    status: str
    product_card_id: int
    count: int
    makespan_sec: int
    operations: tuple[ScheduledOperation, ...]


@dataclass(frozen=True)
class DepartmentPlanningResult:
    department_id: int
    department_name: str
    started_at: datetime
    finished_at: datetime
    plan: ProductionPlan | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if (self.plan is None) == (self.error is None):
            raise ValueError('A department scenario must have either a plan or an error')
        if self.finished_at < self.started_at:
            raise ValueError('Scenario cannot finish before it starts')
        if self.plan and any(o.department_id != self.department_id for o in self.plan.operations):
            raise ValueError('A department scenario must use only its own employees')

