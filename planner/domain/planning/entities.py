"""Result entities produced by the planning application service."""

from dataclasses import dataclass
from datetime import datetime


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


@dataclass(frozen=True)
class ProductionPlan:
    status: str
    product_card_id: int
    count: int
    makespan_sec: int
    operations: tuple[ScheduledOperation, ...]

