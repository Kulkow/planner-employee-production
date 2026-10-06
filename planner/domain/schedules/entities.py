"""Work schedule rules described in docs/employee/employee_work.md."""

from dataclasses import dataclass
from datetime import date, datetime, time


@dataclass(frozen=True)
class WorkSchedule:
    employee_id: int
    work_days: frozenset[int]
    work_start: time
    work_end: time

    def __post_init__(self) -> None:
        if not self.work_days or any(day not in range(7) for day in self.work_days):
            raise ValueError("Work days must use weekday numbers from 0 to 6")
        if self.work_start >= self.work_end:
            raise ValueError("Work shift end must be later than its start")

    def is_work_hours(self, moment: datetime) -> bool:
        return (
            moment.weekday() in self.work_days
            and self.work_start <= moment.time() < self.work_end
        )

    def is_work_day(self, day: date) -> bool:
        return day.weekday() in self.work_days

    @property
    def shift_duration_sec(self) -> int:
        start = datetime.combine(date.min, self.work_start)
        end = datetime.combine(date.min, self.work_end)
        return int((end - start).total_seconds())

    def shift_start_at(self, day: date) -> datetime:
        if not self.is_work_day(day):
            raise ValueError(f"{day.isoformat()} is not a work day")
        return datetime.combine(day, self.work_start)

