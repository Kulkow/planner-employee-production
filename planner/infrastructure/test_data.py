"""Deterministic test data based on the structures from docs/."""

from dataclasses import dataclass
from datetime import date, datetime, time
import random

from planner.application import PlanningRequest
from planner.domain.employees import (
    Department,
    Employee,
    EmployeeEfficiency,
    EmployeeEquipment,
)
from planner.domain.operations import (
    TechOperation,
    TechOperationEquipmentType,
    TechOperationType,
    TechProcess,
    TechProcessStage,
    TechProcessStageGroup,
)
from planner.domain.production import ProductionTask
from planner.domain.schedules import WorkSchedule


DEFAULT_SEED = 20261006
DEFAULT_PLANNING_DAY = date(2026, 10, 5)  # Monday.


@dataclass(frozen=True)
class TestDataSet:
    request: PlanningRequest
    equipment_types: tuple[TechOperationEquipmentType, ...]
    operation_types: tuple[TechOperationType, ...]


def generate_test_data(
    seed: int = DEFAULT_SEED,
    planning_day: date = DEFAULT_PLANNING_DAY,
) -> TestDataSet:
    """Generate four departments, 40 employees and one six-stage process."""

    rng = random.Random(seed)
    department_names = (
        "Раскрой",
        "Механическая обработка",
        "Сборка",
        "Контроль качества",
    )
    equipment_specs = (
        (1, "Лазерный станок", "LASER"),
        (2, "Токарный станок", "LATHE"),
        (3, "Сборочный стенд", "ASSEMBLY"),
        (4, "Измерительный стенд", "QC"),
    )
    operation_specs = (
        (1, "Раскрой детали", 1),
        (2, "Механическая обработка", 2),
        (3, "Сборочная операция", 3),
        (4, "Контрольная операция", 4),
    )

    departments = tuple(
        Department(id=index, name=name)
        for index, name in enumerate(department_names, start=1)
    )
    equipment_types = tuple(
        TechOperationEquipmentType(id=item[0], name=item[1], code=item[2])
        for item in equipment_specs
    )
    operation_types = tuple(
        TechOperationType(id=item[0], name=item[1], rank=item[2])
        for item in operation_specs
    )

    last_names = (
        "Иванов",
        "Петров",
        "Сидоров",
        "Смирнов",
        "Кузнецов",
        "Попов",
        "Васильев",
        "Соколов",
        "Михайлов",
        "Новиков",
    )
    first_names = ("Алексей", "Борис", "Виктор", "Глеб")
    employees: list[Employee] = []
    efficiencies: list[EmployeeEfficiency] = []
    schedules: list[WorkSchedule] = []
    employee_id = 1
    equipment_link_id = 1

    for department, equipment_type, first_name in zip(
        departments, equipment_types, first_names
    ):
        for last_name in last_names:
            equipment = EmployeeEquipment(
                id=equipment_link_id,
                employee_id=employee_id,
                equipment_type_id=equipment_type.id,
            )
            employees.append(
                Employee(
                    id=employee_id,
                    full_name=f"{last_name} {first_name}",
                    position=f"Оператор: {equipment_type.name}",
                    department_id=department.id,
                    equipment=(equipment,),
                )
            )
            efficiencies.append(
                EmployeeEfficiency(
                    id=employee_id,
                    employee_id=employee_id,
                    equipment_type_id=equipment_type.id,
                    percent=rng.randint(60, 90),
                    day=datetime.combine(planning_day, time(8, 30)),
                )
            )
            schedules.append(
                WorkSchedule(
                    employee_id=employee_id,
                    work_days=frozenset(range(5)),
                    work_start=time(8, 30),
                    work_end=time(16, 30),
                )
            )
            employee_id += 1
            equipment_link_id += 1

    stages: list[TechProcessStage] = []
    operation_id = 1
    for stage_number in range(1, 7):
        groups: list[TechProcessStageGroup] = []
        for group_number in range(1, rng.randint(2, 4) + 1):
            operations: list[TechOperation] = []
            for _ in range(rng.randint(2, 5)):
                equipment_index = (operation_id - 1) % len(equipment_types)
                operations.append(
                    TechOperation(
                        id=operation_id,
                        norm_sec=rng.randint(5, 30),
                        type=operation_types[equipment_index],
                        equipment_type=equipment_types[equipment_index],
                    )
                )
                operation_id += 1
            groups.append(
                TechProcessStageGroup(
                    name=f"Этап {stage_number}. Группа {group_number}",
                    operations=tuple(operations),
                )
            )
        stages.append(
            TechProcessStage(stage=stage_number, groups=tuple(groups))
        )

    process = TechProcess(id=1, product_card_id=1001, stages=tuple(stages))
    task = ProductionTask(
        product_card_id=process.product_card_id,
        count=1,
        tech_process=process,
    )
    request = PlanningRequest(
        task=task,
        departments=departments,
        employees=tuple(employees),
        efficiencies=tuple(efficiencies),
        work_schedules=tuple(schedules),
        planning_day=planning_day,
    )
    return TestDataSet(
        request=request,
        equipment_types=equipment_types,
        operation_types=operation_types,
    )
