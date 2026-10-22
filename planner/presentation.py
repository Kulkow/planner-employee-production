"""JSON presentation shared by job snapshots and completed plans."""

from datetime import datetime, time

from planner.application.planning import PlanningRequest
from planner.domain.jobs import PlanningJob


def job_payload(job: PlanningJob) -> dict[str, object]:
    return {
        'id': job.id,
        'status': job.status.value,
        'productCardId': job.task.product_card_id,
        'count': job.task.count,
        'techProcessId': job.task.tech_process.id,
        'planningDay': job.planning_day.isoformat(),
        'createdAt': job.created_at.isoformat(),
        'startedAt': job.started_at.isoformat() if job.started_at else None,
        'finishedAt': job.finished_at.isoformat() if job.finished_at else None,
        'durationSec': job.duration_sec,
        'resultStatus': job.result.status if job.result else None,
        'error': job.error,
        'metrics': {
            'calculationSeconds': job.metrics.elapsed_seconds,
            'memoryStartBytes': job.metrics.memory_start_bytes,
            'peakRssBytes': job.metrics.peak_rss_bytes,
            'memoryGrowthBytes': job.metrics.peak_rss_bytes - job.metrics.memory_start_bytes,
            'memoryScope': job.metrics.memory_scope,
        } if job.metrics else None,
    }


def operations_payload(plan) -> list[dict[str, object]]:
    return [
        {
            "unit": item.unit_number,
            "stage": item.stage,
            "group": item.group_name,
            "operationId": item.operation_id,
            "employeeId": item.employee_id,
            "employee": item.employee_name,
            "departmentId": item.department_id,
            "department": item.department_name,
            "equipment": item.equipment_code,
            "efficiency": item.efficiency_percent,
            "duration": item.duration_sec,
            "departmentOptions": [
                {
                    "departmentId": option.department_id,
                    "department": option.department_name,
                    "minDuration": option.min_duration_sec,
                    "qualifiedEmployees": option.qualified_employee_count,
                    "selected": option.department_id == item.department_id,
                }
                for option in item.department_options
            ],
            "start": item.starts_at.isoformat(),
            "end": item.ends_at.isoformat(),
        }
        for item in (plan.operations if plan else ())
    ]


def plan_payload(job: PlanningJob, request: PlanningRequest) -> dict[str, object]:
    plan = job.result
    operations = operations_payload(plan)
    origin = datetime.combine(request.planning_day, min((s.work_start for s in request.work_schedules), default=time.min))
    outcomes = {item.department_id: item for item in job.department_results}
    equipment_types = {
        operation.equipment_type.id: operation.equipment_type
        for operation in request.task.tech_process.operations
    }
    efficiencies = {
        (item.employee_id, item.equipment_type_id): item.percent
        for item in request.efficiencies
    }
    comparison = []
    if request.compare_departments:
        for index, department in enumerate(request.departments):
            item = outcomes.get(department.id)
            scenario = item.plan if item else None
            scenario_operations = scenario.operations if scenario else ()
            end = max((operation.ends_at for operation in scenario_operations), default=None)
            comparison.append({
                'departmentId': department.id,
                'department': department.name,
                'employees': [
                    {
                        'id': employee.id,
                        'name': employee.full_name,
                        'workloads': [
                            {
                                'employeeId': item.employee_id,
                                'date': item.date.isoformat(),
                                'plannedSeconds': item.planned_seconds,
                                'allocatedSeconds': item.allocated_seconds,
                                'availableSeconds': item.available_seconds,
                            }
                            for item in sorted(request.employee_workloads, key=lambda item: item.date)
                            if item.employee_id == employee.id
                        ],
                        'efficiencies': [
                            {
                                'equipmentTypeId': qualification.equipment_type_id,
                                'equipment': equipment_types[qualification.equipment_type_id].name
                                if qualification.equipment_type_id in equipment_types
                                else f'Оборудование №{qualification.equipment_type_id}',
                                'percent': efficiencies.get((employee.id, qualification.equipment_type_id)),
                            }
                            for qualification in employee.equipment
                        ],
                    }
                    for employee in request.employees
                    if employee.department_id == department.id
                ],
                'status': ('completed' if scenario else 'failed') if item else (
                    'running' if job.status.value == 'running' and (
                        department.id in job.running_department_ids if job.running_department_ids else index == len(outcomes)
                    ) else 'pending'),
                'solverStatus': scenario.status if scenario else None,
                'error': item.error if item else None,
                'selected': scenario is not None and scenario == job.result,
                'calculationStartedAt': item.started_at.isoformat() if item else None,
                'calculationFinishedAt': item.finished_at.isoformat() if item else None,
                'calculationSec': (item.finished_at - item.started_at).total_seconds() if item else None,
                'makespan': scenario.makespan_sec if scenario else None,
                'elapsedSec': int((end - origin).total_seconds()) if end else None,
                'workSec': sum(operation.duration_sec for operation in scenario_operations) if scenario else None,
                'start': min((operation.starts_at for operation in scenario_operations), default=origin).isoformat() if scenario else None,
                'end': end.isoformat() if end else None,
                'operations': operations_payload(scenario),
            })

    return {
        "job": job_payload(job),
        "comparisonMode": request.compare_departments,
        "horizonDays": request.horizon_days,
        "planningOrigin": origin.isoformat(),
        "completedDepartments": len(job.department_results),
        "runningDepartmentIds": list(job.running_department_ids),
        "departmentComparison": comparison,
        "status": plan.status if plan else None,
        "productCardId": request.task.product_card_id,
        "count": request.task.count,
        "planningDay": request.planning_day.isoformat(),
        "makespan": plan.makespan_sec if plan else None,
        "operations": operations,
        "techProcess": {
            "id": request.task.tech_process.id,
            "productCardId": request.task.product_card_id,
            "stages": [
                {
                    "stage": stage.stage,
                    "groups": [
                        {
                            "name": group.name,
                            "operations": [
                                {
                                    "id": operation.id,
                                    "name": operation.type.name,
                                    "equipment": operation.equipment_type.name,
                                    "equipmentCode": operation.equipment_type.code,
                                    "normSec": operation.norm_sec,
                                }
                                for operation in group.operations
                            ],
                        }
                        for group in stage.groups
                    ],
                }
                for stage in request.task.tech_process.stages
            ],
        },
        "departments": [item.name for item in request.departments],
        "employeeCount": len(request.employees),
    }
