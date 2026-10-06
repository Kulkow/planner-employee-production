"""Production task aggregate described in docs/production."""

from dataclasses import dataclass

from planner.domain.operations import TechProcess


@dataclass(frozen=True)
class ProductionTask:
    product_card_id: int
    count: int
    tech_process: TechProcess

    def __post_init__(self) -> None:
        if self.count <= 0:
            raise ValueError("Production count must be positive")
        if self.product_card_id != self.tech_process.product_card_id:
            raise ValueError("Product card must match the technological process")

