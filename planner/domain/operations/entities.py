"""Technological process aggregate described in docs/operations."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TechOperationType:
    id: int
    name: str
    rank: int


@dataclass(frozen=True)
class TechOperationEquipmentType:
    id: int
    name: str
    code: str


@dataclass(frozen=True)
class TechOperation:
    id: int
    norm_sec: int
    type: TechOperationType
    equipment_type: TechOperationEquipmentType

    def __post_init__(self) -> None:
        if self.norm_sec <= 0:
            raise ValueError("Operation duration must be positive")


@dataclass(frozen=True)
class TechProcessStageGroup:
    name: str
    operations: tuple[TechOperation, ...]

    def __post_init__(self) -> None:
        if not self.operations:
            raise ValueError("A process group must contain at least one operation")


@dataclass(frozen=True)
class TechProcessStage:
    stage: int
    groups: tuple[TechProcessStageGroup, ...]

    def __post_init__(self) -> None:
        if not self.groups:
            raise ValueError("A process stage must contain at least one group")

    @property
    def operations(self) -> tuple[TechOperation, ...]:
        return tuple(
            operation for group in self.groups for operation in group.operations
        )


@dataclass(frozen=True)
class TechProcess:
    id: int
    product_card_id: int
    stages: tuple[TechProcessStage, ...]

    def __post_init__(self) -> None:
        if not self.stages:
            raise ValueError("A technological process must contain at least one stage")
        stage_numbers = [stage.stage for stage in self.stages]
        if stage_numbers != sorted(stage_numbers) or len(stage_numbers) != len(
            set(stage_numbers)
        ):
            raise ValueError("Process stages must have unique ascending numbers")

    @property
    def operations(self) -> tuple[TechOperation, ...]:
        return tuple(operation for stage in self.stages for operation in stage.operations)

