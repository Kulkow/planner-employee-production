"""Composition root for the production planning demonstration."""

from collections import Counter

from planner.application import ProductionPlanningService
from planner.infrastructure.cp_sat_planner import CpSatProductionPlanner
from planner.infrastructure.test_data import generate_test_data


def main() -> None:
    data = generate_test_data()
    request = data.request
    process = request.task.tech_process

    print("TEST DATA")
    print(
        f"departments={len(request.departments)} employees={len(request.employees)} "
        f"stages={len(process.stages)} operations={len(process.operations)}"
    )
    efficiencies = {
        (item.employee_id, item.equipment_type_id): item.percent
        for item in request.efficiencies
    }
    equipment_codes = {
        equipment.id: equipment.code for equipment in data.equipment_types
    }
    for department in request.departments:
        print(f"\n[{department.name}]")
        for employee in request.employees:
            if employee.department_id == department.id:
                equipment_efficiencies = ", ".join(
                    f"{equipment_codes[item.equipment_type_id]}="
                    f"{efficiencies[(employee.id, item.equipment_type_id)]}%"
                    for item in employee.equipment
                )
                print(
                    f"  employee={employee.id:02d} {employee.full_name}; "
                    f"efficiency=[{equipment_efficiencies}]"
                )

    print("\nTECH PROCESS")
    for stage in process.stages:
        operation_count = sum(len(group.operations) for group in stage.groups)
        print(
            f"stage={stage.stage} groups={len(stage.groups)} "
            f"operations={operation_count}"
        )

    service = ProductionPlanningService(CpSatProductionPlanner())
    plan = service.create_plan(request)

    print("\nPRODUCTION PLAN")
    print(
        f"status={plan.status} product={plan.product_card_id} "
        f"count={plan.count} makespan={plan.makespan_sec} sec"
    )
    for operation in plan.operations:
        print(
            f"{operation.starts_at:%H:%M:%S}-{operation.ends_at:%H:%M:%S} "
            f"stage={operation.stage} operation={operation.operation_id:03d} "
            f"employee={operation.employee_id:02d} "
            f"department={operation.department_name} "
            f"efficiency={operation.efficiency_percent}% "
            f"duration={operation.duration_sec}s"
        )

    assignment_counts = Counter(
        operation.department_name for operation in plan.operations
    )
    print("\nASSIGNMENTS BY DEPARTMENT")
    for department_name, count in sorted(assignment_counts.items()):
        print(f"{department_name}: {count}")


if __name__ == "__main__":
    main()
