"""OR-Tools CP-SAT adapter for the production planning port."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time, timedelta
import math
from typing import Any

from ortools.sat.python import cp_model

from planner.application import PlanningRequest
from planner.domain.employees import Employee
from planner.domain.operations import TechOperation
from planner.domain.planning import DepartmentOption, ProductionPlan, ScheduledOperation


SECONDS_PER_DAY = 24 * 60 * 60


@dataclass(frozen=True)
class _CandidateAssignment:
    employee: Employee
    selected: Any
    interval: Any
    duration_sec: int
    efficiency_percent: int


@dataclass(frozen=True)
class _OperationVariables:
    start: Any
    end: Any
    candidates: tuple[_CandidateAssignment, ...]


class _ConstructiveSolution:
    def __init__(self):
        self.values: dict[int, int] = {}
        self.bindings: list[tuple[Any, int]] = []

    def set(self, variable, value: int):
        self.values[variable.index] = value
        self.bindings.append((variable, value))

    def value(self, variable) -> int:
        return self.values[variable.index]


def _construct_department_schedule(request, variables, schedules, workloads):
    """A valid incumbent for one capacity-one brigade, not an optimality claim."""
    if len(request.departments) != 1:
        return None
    solution = _ConstructiveSolution()
    used = defaultdict(int)
    ready = 0
    # Insertion order is unit -> stage -> group -> operation, satisfying all
    # precedence constraints while serializing the department's work.
    for operation in variables.values():
        choices = []
        for candidate in operation.candidates:
            employee_id = candidate.employee.id
            schedule = schedules[employee_id]
            for offset in range(ready // SECONDS_PER_DAY, request.horizon_days):
                day = request.planning_day + timedelta(days=offset)
                if not schedule.is_work_day(day):
                    continue
                workload = workloads.get((employee_id, day))
                available = workload.available_seconds if workload else schedule.shift_duration_sec
                if used[(employee_id, day)] + candidate.duration_sec > available:
                    continue
                start = max(ready, offset * SECONDS_PER_DAY + _seconds_since_midnight(schedule.work_start))
                end = start + candidate.duration_sec
                if end <= offset * SECONDS_PER_DAY + _seconds_since_midnight(schedule.work_end):
                    choices.append((end, start, employee_id, candidate, day))
                    break
        if not choices:
            return None
        end, start, employee_id, assignment, day = min(choices, key=lambda choice: choice[:3])
        solution.set(operation.start, start)
        solution.set(operation.end, end)
        for candidate in operation.candidates:
            solution.set(candidate.selected, int(candidate is assignment))
        used[(employee_id, day)] += assignment.duration_sec
        ready = end
    return solution


class CpSatProductionPlanner:
    """Assign operations to qualified employees and minimize completion time."""

    def __init__(self, max_time_sec: float = 20.0) -> None:
        self._max_time_sec = max_time_sec

    def plan(self, request: PlanningRequest) -> ProductionPlan:
        model = cp_model.CpModel()
        employees = {employee.id: employee for employee in request.employees}
        departments = {
            department.id: department for department in request.departments
        }
        efficiencies = {
            (efficiency.employee_id, efficiency.equipment_type_id): efficiency
            for efficiency in request.efficiencies
        }
        schedules = {
            schedule.employee_id: schedule for schedule in request.work_schedules
        }
        horizon_sec = request.horizon_days * SECONDS_PER_DAY
        workloads = {
            (item.employee_id, item.date): item
            for item in request.employee_workloads
            if 0 <= (item.date - request.planning_day).days < request.horizon_days
        }
        daily_work_terms: dict[tuple[int, Any], list[Any]] = defaultdict(list)
        process = request.task.tech_process

        operation_locations: dict[int, tuple[int, str, TechOperation]] = {}
        for stage in process.stages:
            for group in stage.groups:
                for operation in group.operations:
                    if operation.id in operation_locations:
                        raise ValueError(f"Duplicate operation id: {operation.id}")
                    operation_locations[operation.id] = (
                        stage.stage,
                        group.name,
                        operation,
                    )

        variables: dict[tuple[int, int], _OperationVariables] = {}
        intervals_by_employee: dict[int, list[Any]] = defaultdict(list)
        intervals_by_department: dict[int, list[Any]] = defaultdict(list)
        duration_terms: list[Any] = []
        max_duration_sum = 0

        for unit_number in range(1, request.task.count + 1):
            for operation in process.operations:
                key = (unit_number, operation.id)
                suffix = f"u{unit_number}_o{operation.id}"
                start = model.new_int_var(0, horizon_sec, f"start_{suffix}")
                end = model.new_int_var(0, horizon_sec, f"end_{suffix}")
                candidates: list[_CandidateAssignment] = []
                day_flags: dict[int, Any] = {}
                operation_day = None
                if workloads:
                    operation_day = model.new_int_var(0, request.horizon_days - 1, f'day_{suffix}')
                    model.add_division_equality(operation_day, start, SECONDS_PER_DAY)

                for employee in request.employees:
                    schedule = schedules[employee.id]
                    if not employee.can_use(operation.equipment_type.id):
                        continue

                    efficiency = efficiencies[
                        (employee.id, operation.equipment_type.id)
                    ].percent
                    duration_sec = math.ceil(operation.norm_sec * 100 / efficiency)
                    if duration_sec > schedule.shift_duration_sec:
                        continue

                    windows = [
                        [offset * SECONDS_PER_DAY + _seconds_since_midnight(schedule.work_start),
                         offset * SECONDS_PER_DAY + _seconds_since_midnight(schedule.work_end) - duration_sec]
                        for offset in range(request.horizon_days)
                        if schedule.is_work_day(request.planning_day + timedelta(days=offset))
                        and (
                            (workload := workloads.get((employee.id, request.planning_day + timedelta(days=offset)))) is None
                            or duration_sec <= workload.available_seconds
                        )
                    ]
                    if not windows:
                        continue

                    selected = model.new_bool_var(
                        f"employee_{employee.id}_{suffix}"
                    )
                    candidate_end = model.new_int_var(
                        0, horizon_sec, f"candidate_end_{employee.id}_{suffix}"
                    )
                    interval = model.new_optional_interval_var(
                        start,
                        duration_sec,
                        candidate_end,
                        selected,
                        f"interval_{employee.id}_{suffix}",
                    )
                    # Each operation must fit entirely in one working shift;
                    # nights and weekends are excluded from its start domain.
                    model.add_linear_expression_in_domain(
                        start, cp_model.Domain.from_intervals(windows),
                    ).only_enforce_if(selected)
                    model.add(end == candidate_end).only_enforce_if(selected)

                    assignment = _CandidateAssignment(
                        employee=employee,
                        selected=selected,
                        interval=interval,
                        duration_sec=duration_sec,
                        efficiency_percent=efficiency,
                    )
                    candidates.append(assignment)
                    intervals_by_employee[employee.id].append(interval)
                    intervals_by_department[employee.department_id].append(interval)
                    for (member_id, day), workload in workloads.items():
                        if member_id != employee.id:
                            continue
                        offset = (day - request.planning_day).days
                        if offset not in day_flags:
                            on_day = model.new_bool_var(f'on_day_{offset}_{suffix}')
                            model.add(operation_day == offset).only_enforce_if(on_day)
                            model.add(operation_day != offset).only_enforce_if(on_day.Not())
                            day_flags[offset] = on_day
                        assigned_on_day = model.new_bool_var(f'assigned_day_{employee.id}_{offset}_{suffix}')
                        model.add(assigned_on_day <= selected)
                        model.add(assigned_on_day <= day_flags[offset])
                        model.add(assigned_on_day >= selected + day_flags[offset] - 1)
                        daily_work_terms[(employee.id, day)].append(duration_sec * assigned_on_day)
                    duration_terms.append(duration_sec * selected)

                if not candidates:
                    raise ValueError(
                        "Нет доступного квалифицированного исполнителя для операции "
                        f"{operation.id} ({operation.equipment_type.code}) в выбранном горизонте"
                    )
                model.add_exactly_one(
                    [candidate.selected for candidate in candidates]
                )
                max_duration_sum += max(
                    candidate.duration_sec for candidate in candidates
                )
                variables[key] = _OperationVariables(
                    start=start,
                    end=end,
                    candidates=tuple(candidates),
                )

        # Even unlimited parallel resources cannot shorten a sequential group
        # or start the next stage before the previous stage has finished.
        minimum_duration = sum(
            max(
                sum(
                    min(candidate.duration_sec for candidate in variables[(1, operation.id)].candidates)
                    for operation in group.operations
                )
                for group in stage.groups
            )
            for stage in process.stages
        )
        available_schedules = [
            schedules[candidate.employee.id]
            for operation in variables.values()
            for candidate in operation.candidates
        ]
        available_span = max(
            _seconds_since_midnight(schedule.work_end) for schedule in available_schedules
        ) - min(
            _seconds_since_midnight(schedule.work_start) for schedule in available_schedules
        )
        available_span += (request.horizon_days - 1) * SECONDS_PER_DAY
        if minimum_duration > available_span:
            raise ValueError(
                "План не помещается в рабочий день: даже без ожидания сотрудников "
                f"техпроцесс одного изделия требует минимум {_format_duration(minimum_duration)}, "
                f"доступно {_format_duration(available_span)}. "
                "Увеличьте горизонт планирования."
            )

        for intervals in intervals_by_employee.values():
            model.add_no_overlap(intervals)
        # A brigade is a Department, with capacity one regardless of headcount.
        # Exactly one selected employee also means exactly one brigade per operation.
        for intervals in intervals_by_department.values():
            model.add_no_overlap(intervals)
        for key, terms in daily_work_terms.items():
            model.add(sum(terms) <= workloads[key].available_seconds)

        for unit_number in range(1, request.task.count + 1):
            for stage in process.stages:
                for group in stage.groups:
                    for previous, current in zip(
                        group.operations, group.operations[1:]
                    ):
                        model.add(
                            variables[(unit_number, current.id)].start
                            >= variables[(unit_number, previous.id)].end
                        )

            for previous_stage, current_stage in zip(
                process.stages, process.stages[1:]
            ):
                for previous in previous_stage.operations:
                    for current in current_stage.operations:
                        model.add(
                            variables[(unit_number, current.id)].start
                            >= variables[(unit_number, previous.id)].end
                        )

        makespan_end = model.new_int_var(0, horizon_sec, "makespan_end")
        model.add_max_equality(
            makespan_end, [operation.end for operation in variables.values()]
        )

        # Lexicographic priorities: completion time, then total labor time.
        # Avoid multiplying by a horizon-sized third weight (int64 overflow).
        model.minimize(makespan_end * (max_duration_sum + 1) + sum(duration_terms))

        constructive = _construct_department_schedule(request, variables, schedules, workloads)
        if constructive is not None:
            for variable, value in constructive.bindings:
                model.add_hint(variable, value)

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self._max_time_sec
        solver.parameters.num_search_workers = 1
        solver.parameters.random_seed = 0
        # Finding the first valid assignment is considerably easier than proving
        # the optimum.  Keep that assignment as a fallback: otherwise a busy or
        # slower host can return UNKNOWN at the time limit even though a usable
        # schedule exists.
        feasibility_model = model.clone()
        feasibility_model.clear_objective()
        feasibility_solver = cp_model.CpSolver()
        feasibility_solver.parameters.max_time_in_seconds = min(
            self._max_time_sec, 5.0
        )
        feasibility_solver.parameters.num_search_workers = 1
        feasibility_solver.parameters.random_seed = 0
        feasibility_status = feasibility_solver.solve(feasibility_model)

        if feasibility_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            model.clear_hints()
            for operation_variables in variables.values():
                model.add_hint(
                    operation_variables.start,
                    feasibility_solver.value(operation_variables.start),
                )
                model.add_hint(
                    operation_variables.end,
                    feasibility_solver.value(operation_variables.end),
                )
                for candidate in operation_variables.candidates:
                    model.add_hint(
                        candidate.selected,
                        feasibility_solver.value(candidate.selected),
                    )

        optimization_status = solver.solve(model)
        if optimization_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            status = optimization_status
        elif feasibility_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            solver = feasibility_solver
            # ``OPTIMAL`` here only means that the feasibility model (which has
            # no objective) was solved.  Do not mislabel the returned fallback
            # as an optimal production plan.
            status = cp_model.FEASIBLE
        elif constructive is not None and feasibility_status == optimization_status == cp_model.UNKNOWN:
            solver = constructive
            status = cp_model.FEASIBLE
        else:
            if cp_model.INFEASIBLE in (feasibility_status, optimization_status):
                raise RuntimeError(
                    "Не удалось составить план в пределах горизонта планирования: "
                    "ограничения по сотрудникам, времени и порядку операций несовместимы."
                )
            if cp_model.MODEL_INVALID in (feasibility_status, optimization_status):
                raise RuntimeError("Ошибка модели планирования. Проверьте параметры расчёта.")
            raise RuntimeError(
                "За отведённое время решатель не нашёл план. "
                "Это не означает, что план невозможен. "
                "Попробуйте уменьшить количество изделий или увеличить время расчёта."
            )

        day_start = datetime.combine(request.planning_day, time.min)
        scheduled: list[ScheduledOperation] = []
        for key, operation_variables in variables.items():
            unit_number, operation_id = key
            stage_number, group_name, operation = operation_locations[operation_id]
            assignment = next(
                candidate
                for candidate in operation_variables.candidates
                if solver.value(candidate.selected) == 1
            )
            employee = employees[assignment.employee.id]
            department = departments[employee.department_id]
            start_sec = solver.value(operation_variables.start)
            end_sec = solver.value(operation_variables.end)
            candidates_by_department: dict[int, list[_CandidateAssignment]] = defaultdict(list)
            for candidate in operation_variables.candidates:
                candidates_by_department[candidate.employee.department_id].append(candidate)
            scheduled.append(
                ScheduledOperation(
                    unit_number=unit_number,
                    stage=stage_number,
                    group_name=group_name,
                    operation_id=operation.id,
                    employee_id=employee.id,
                    employee_name=employee.full_name,
                    department_id=department.id,
                    department_name=department.name,
                    equipment_code=operation.equipment_type.code,
                    efficiency_percent=assignment.efficiency_percent,
                    norm_sec=operation.norm_sec,
                    duration_sec=assignment.duration_sec,
                    starts_at=day_start + timedelta(seconds=start_sec),
                    ends_at=day_start + timedelta(seconds=end_sec),
                    department_options=tuple(
                        DepartmentOption(
                            department_id=department_id,
                            department_name=departments[department_id].name,
                            min_duration_sec=min(candidate.duration_sec for candidate in candidates),
                            qualified_employee_count=len(candidates),
                        )
                        for department_id, candidates in sorted(candidates_by_department.items())
                    ),
                )
            )

        scheduled.sort(
            key=lambda item: (
                item.starts_at,
                item.stage,
                item.group_name,
                item.operation_id,
            )
        )
        first_start = min(operation.starts_at for operation in scheduled)
        last_end = max(operation.ends_at for operation in scheduled)
        return ProductionPlan(
            status=_status_name(status),
            product_card_id=request.task.product_card_id,
            count=request.task.count,
            makespan_sec=int((last_end - first_start).total_seconds()),
            operations=tuple(scheduled),
        )


def _seconds_since_midnight(value: time) -> int:
    return value.hour * 3600 + value.minute * 60 + value.second


def _format_duration(seconds: int) -> str:
    minutes = math.ceil(seconds / 60)
    return f"{minutes // 60} ч {minutes % 60} мин"


def _status_name(status: Any) -> str:
    """Read the v9.15 enum directly, avoiding its status_name compatibility issue."""

    return str(getattr(status, "name", status))
