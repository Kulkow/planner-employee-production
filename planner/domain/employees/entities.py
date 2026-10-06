"""Employee aggregate entities described in docs/employee."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Department:
    id: int
    name: str


@dataclass(frozen=True)
class EmployeeEquipment:
    id: int
    employee_id: int
    equipment_type_id: int


@dataclass(frozen=True)
class Employee:
    id: int
    full_name: str
    position: str
    department_id: int
    equipment: tuple[EmployeeEquipment, ...]

    def can_use(self, equipment_type_id: int) -> bool:
        return any(
            item.equipment_type_id == equipment_type_id for item in self.equipment
        )


@dataclass(frozen=True)
class EmployeeEfficiency:
    id: int
    employee_id: int
    equipment_type_id: int
    percent: int
    day: datetime

    def __post_init__(self) -> None:
        if not 1 <= self.percent <= 100:
            raise ValueError("Employee efficiency must be between 1 and 100 percent")
