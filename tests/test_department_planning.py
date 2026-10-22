"""A Department is one brigade; it cannot run two operations at once."""

from dataclasses import replace
from datetime import date, datetime, time
import unittest

from planner.application import PlanningRequest, ProductionPlanningService
from planner.domain.employees import Department, Employee, EmployeeEfficiency, EmployeeEquipment
from planner.domain.operations import TechOperation, TechOperationEquipmentType, TechOperationType, TechProcess, TechProcessStage, TechProcessStageGroup
from planner.domain.production import ProductionTask
from planner.domain.schedules import WorkSchedule
from planner.infrastructure.cp_sat_planner import CpSatProductionPlanner
from planner.presentation import plan_payload
from planner.application.jobs import new_job


def request_for_test():
    equipment = TechOperationEquipmentType(1, 'Станок', 'MACHINE')
    operation_type = TechOperationType(1, 'Обработка', 1)
    process = TechProcess(1, 1, (TechProcessStage(1, (
        TechProcessStageGroup('Группа A', (TechOperation(1, 100, operation_type, equipment),)),
        TechProcessStageGroup('Группа B', (TechOperation(2, 100, operation_type, equipment),)),
    )),))
    day = date(2026, 10, 5)
    employees = tuple(Employee(i, f'Сотрудник {i}', 'Оператор', 1 if i < 3 else 2,
                               (EmployeeEquipment(i, i, 1),)) for i in (1, 2, 3))
    return PlanningRequest(
        task=ProductionTask(1, 2, process),
        departments=(Department(1, 'Бригада 1'), Department(2, 'Бригада 2')),
        employees=employees,
        efficiencies=tuple(EmployeeEfficiency(i, i, 1, 100 if i < 3 else 80,
                                              datetime.combine(day, time(8, 30))) for i in (1, 2, 3)),
        work_schedules=tuple(WorkSchedule(i, frozenset(range(5)), time(8, 30), time(16, 30)) for i in (1, 2, 3)),
        planning_day=day,
    )


class DepartmentPlanningTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.request = request_for_test()
        cls.plan = ProductionPlanningService(CpSatProductionPlanner(max_time_sec=2)).create_plan(cls.request)

    def test_operation_has_exactly_one_brigade(self):
        self.assertEqual(len(self.plan.operations), 4)
        self.assertEqual(len({(o.unit_number, o.operation_id) for o in self.plan.operations}), 4)
        departments = {e.id: e.department_id for e in self.request.employees}
        for operation in self.plan.operations:
            self.assertEqual(operation.department_id, departments[operation.employee_id])

    def test_brigade_has_no_overlaps_even_with_different_employees(self):
        for department in self.request.departments:
            operations = sorted((o for o in self.plan.operations if o.department_id == department.id), key=lambda o: o.starts_at)
            for first, second in zip(operations, operations[1:]):
                self.assertLessEqual(first.ends_at, second.starts_at)
        self.assertEqual({o.department_id for o in self.plan.operations}, {1, 2})

    def test_two_specialists_in_same_department_cannot_work_in_parallel(self):
        request = self.request
        process = request.task.tech_process
        second_equipment = TechOperationEquipmentType(2, 'Другой станок', 'OTHER')
        groups = list(process.stages[0].groups)
        groups[1] = replace(groups[1], operations=(replace(groups[1].operations[0], equipment_type=second_equipment),))
        process = replace(process, stages=(replace(process.stages[0], groups=tuple(groups)),))
        request = replace(request,
            task=replace(request.task, count=1, tech_process=process),
            departments=(request.departments[0],),
            employees=(request.employees[0], replace(request.employees[1], equipment=(EmployeeEquipment(2, 2, 2),))),
            efficiencies=(request.efficiencies[0], replace(request.efficiencies[1], equipment_type_id=2)),
            work_schedules=request.work_schedules[:2],
        )
        plan = ProductionPlanningService(CpSatProductionPlanner(max_time_sec=2)).create_plan(request)
        self.assertEqual({o.employee_id for o in plan.operations}, {1, 2})
        self.assertEqual(plan.makespan_sec, 200)

    def test_comparison_contains_only_eligible_departments_and_one_selection(self):
        job = new_job(self.request).start(datetime.now().astimezone())
        job = job.complete(self.plan, datetime.now().astimezone())
        payload = plan_payload(job, self.request)
        for operation in payload['operations']:
            options = operation['departmentOptions']
            self.assertEqual({o['departmentId'] for o in options}, {1, 2})
            self.assertEqual(sum(o['selected'] for o in options), 1)
            self.assertEqual(next(o['departmentId'] for o in options if o['selected']), operation['departmentId'])
            self.assertEqual({o['departmentId']: o['minDuration'] for o in options}, {1: 100, 2: 125})
            self.assertEqual({o['departmentId']: o['qualifiedEmployees'] for o in options}, {1: 2, 2: 1})


class DepartmentComparisonTest(unittest.TestCase):
    def generate(self, request):
        from planner.application.jobs import PlanningJobService
        from planner.infrastructure.planning_jobs import InMemoryPlanningJobRepository
        from unittest.mock import Mock
        planning = Mock(wraps=ProductionPlanningService(CpSatProductionPlanner(max_time_sec=2)))
        repository = InMemoryPlanningJobRepository()
        job = PlanningJobService(planning, repository).generate(replace(request, compare_departments=True))
        return job, planning

    def test_runs_whole_job_for_each_department_sequentially(self):
        request = request_for_test()
        job, planning = self.generate(request)
        self.assertEqual(job.status.value, 'completed')
        self.assertEqual(len(job.department_results), 2)
        self.assertEqual([call.args[0].departments[0].id for call in planning.create_plan.call_args_list], [1, 2])
        for call, outcome in zip(planning.create_plan.call_args_list, job.department_results):
            isolated = call.args[0]
            self.assertEqual(isolated.task, request.task)
            self.assertEqual(isolated.planning_day, request.planning_day)
            self.assertEqual(isolated.horizon_days, request.horizon_days)
            self.assertFalse(isolated.compare_departments)
            self.assertTrue(all(e.department_id == outcome.department_id for e in isolated.employees))
            self.assertEqual(len(outcome.plan.operations), 4)
            self.assertEqual({o.department_id for o in outcome.plan.operations}, {outcome.department_id})
        self.assertLessEqual(job.department_results[0].finished_at, job.department_results[1].started_at)
        self.assertEqual([item.plan.makespan_sec for item in job.department_results], [400, 500])
        payload = plan_payload(job, replace(request, compare_departments=True))
        self.assertEqual([item['elapsedSec'] for item in payload['departmentComparison']], [400, 500])
        self.assertEqual(sum(item['selected'] for item in payload['departmentComparison']), 1)
        self.assertEqual({o.department_id for o in job.result.operations}, {1})

    def test_failed_department_does_not_discard_other_department_plan(self):
        request = request_for_test()
        request = replace(request, employees=tuple(
            replace(e, equipment=(EmployeeEquipment(e.id, e.id, 99),)) if e.department_id == 2 else e
            for e in request.employees
        ), efficiencies=tuple(replace(e, equipment_type_id=99) if e.employee_id == 3 else e for e in request.efficiencies))
        job, _ = self.generate(request)
        self.assertEqual(job.status.value, 'completed')
        self.assertIsNotNone(job.department_results[0].plan)
        self.assertIsNotNone(job.department_results[1].error)
        self.assertIsNone(job.department_results[1].plan)

    def test_all_failed_departments_preserve_individual_errors(self):
        job, _ = self.generate(replace(request_for_test(), planning_day=date(2026, 10, 10)))
        self.assertEqual(job.status.value, 'failed')
        self.assertIsNone(job.result)
        self.assertEqual(len(job.department_results), 2)
        self.assertTrue(all(item.error for item in job.department_results))

    def test_multi_day_schedule_obeys_shift_and_skips_weekend(self):
        request = request_for_test()
        # Two six-hour operations: they cannot fit in Friday's eight-hour shift.
        process = request.task.tech_process
        process = replace(process, stages=tuple(replace(stage, groups=tuple(
            replace(group, operations=tuple(replace(operation, norm_sec=21600) for operation in group.operations))
            for group in stage.groups)) for stage in process.stages))
        request = replace(request, task=replace(request.task, count=1, tech_process=process),
                          planning_day=date(2026, 10, 9), horizon_days=4)
        job, _ = self.generate(request)
        self.assertEqual(job.status.value, 'completed')
        for outcome in job.department_results:
            self.assertIsNotNone(outcome.plan)
            self.assertEqual({o.starts_at.date() for o in outcome.plan.operations}, {date(2026, 10, 9), date(2026, 10, 12)})
            for operation in outcome.plan.operations:
                self.assertEqual(operation.starts_at.date(), operation.ends_at.date())
                self.assertGreaterEqual(operation.starts_at.time(), time(8, 30))
                self.assertLessEqual(operation.ends_at.time(), time(16, 30))
