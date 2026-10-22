"""Planning job lifecycle and application orchestration."""

from datetime import datetime, timedelta, timezone
import unittest

from planner.application.jobs import PlanningJobService
from planner.domain.jobs import JobStatus, PlanningJob
from planner.domain.planning import ProductionPlan
from planner.infrastructure.planning_jobs import InMemoryPlanningJobRepository
from planner.infrastructure.test_data import generate_test_data


class PlanningJobTest(unittest.TestCase):
    def setUp(self):
        self.request = generate_test_data().request
        self.now = datetime.now(timezone.utc)
        self.job = PlanningJob('test', self.request.task, self.request.planning_day, self.now)
        self.plan = ProductionPlan('FEASIBLE', self.request.task.product_card_id, self.request.task.count, 0, ())

    def test_lifecycle_and_duration(self):
        running = self.job.start(self.now)
        done = running.complete(self.plan, self.now + timedelta(seconds=2))
        self.assertEqual(done.status, JobStatus.COMPLETED)
        self.assertEqual(done.duration_sec, 2)
        self.assertEqual(done.result, self.plan)
        self.assertIsNone(self.job.started_at)
        with self.assertRaises(ValueError):
            done.start(self.now)
        with self.assertRaises(ValueError):
            self.job.complete(self.plan, self.now)
        with self.assertRaises(ValueError):
            running.fail('error', self.now - timedelta(seconds=1))

    def test_rejects_result_for_another_product(self):
        wrong = ProductionPlan('FEASIBLE', -1, self.plan.count, 0, ())
        with self.assertRaises(ValueError):
            self.job.start(self.now).complete(wrong, self.now)

    def test_service_saves_success_and_failure(self):
        from unittest.mock import Mock
        planning = Mock()
        planning.create_plan.return_value = self.plan
        repository = InMemoryPlanningJobRepository()
        service = PlanningJobService(planning, repository)
        done = service.generate(self.request)
        self.assertEqual(repository.get(done.id).result, self.plan)
        planning.create_plan.side_effect = ValueError('Invalid resources')
        failed = service.generate(self.request)
        self.assertEqual(failed.status, JobStatus.FAILED)
        self.assertEqual(failed.error, 'Invalid resources')
        self.assertIsNotNone(failed.finished_at)
        self.assertIsNone(failed.result)
        self.assertEqual(len(repository.list()), 2)
