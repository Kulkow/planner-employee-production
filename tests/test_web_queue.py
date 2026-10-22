"""FastAPI + real Redis: queue delivery, worker, Pub/Sub and SSE recovery."""

from datetime import datetime, timezone
import os
import threading
import time
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
from redis import Redis
from redis.exceptions import ConnectionError

from planner.application.jobs import PlanningJobService
from planner.domain.jobs import JobStatus
from planner.domain.planning import ProductionPlan
from planner.infrastructure.redis_jobs import RedisPlanningJobs
from planner.web import app
from planner.worker import process_message


@unittest.skipUnless(os.environ.get('REDIS_URL'), 'Set REDIS_URL to run Redis integration tests')
class WebQueueTest(unittest.TestCase):
    def setUp(self):
        self.redis = Redis.from_url(os.environ['REDIS_URL'], decode_responses=True)
        self.prefix = f'test:{uuid4()}'
        self.store = RedisPlanningJobs(self.redis, self.prefix)
        self.client = TestClient(app)
        self.client.__enter__()
        app.state.jobs = self.store
        self.store.ensure_group()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        keys = list(self.redis.scan_iter(f'{self.prefix}:*'))
        if keys:
            self.redis.delete(*keys)
        self.redis.close()

    def submit(self):
        response = self.client.post('/api/jobs', json={'count': 2, 'planning_day': '2026-10-05', 'compare_departments': False})
        self.assertEqual(response.status_code, 202)
        return response.json()

    def test_submission_is_pending_and_input_snapshot_round_trips(self):
        data = self.submit()
        job_id = data['job']['id']
        self.assertEqual(data['job']['status'], 'pending')
        self.assertIsNone(data['job']['startedAt'])
        request = self.store.get_request(job_id)
        self.assertEqual(request.task.count, 2)
        self.assertIsInstance(request.work_schedules[0].work_days, frozenset)
        self.assertEqual(request.task, self.store.get(job_id).task)
        response = self.client.get(data['resultUrl'])
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['techProcess']['stages'])
        self.assertEqual(response.json()['operations'], [])
        self.assertEqual(self.client.get('/api/jobs').json()[0]['id'], job_id)

    def test_validation_and_missing_job(self):
        for count in (0, 31, True, '2'):
            self.assertEqual(self.client.post('/api/jobs', json={'count': count}).status_code, 422)
        self.assertEqual(self.client.post('/api/jobs', json={'planning_day': 'bad'}).status_code, 422)
        key = uuid4()
        self.assertEqual(self.client.get(f'/api/jobs/{key}').status_code, 404)
        self.assertEqual(self.client.get(f'/api/jobs/{key}/events').status_code, 404)

    def test_redis_failure_returns_503(self):
        with patch.object(self.store, 'enqueue', side_effect=ConnectionError()):
            self.assertEqual(self.client.post('/api/jobs', json={}).status_code, 503)

    def test_live_sse_receives_worker_completion_and_reconnect_snapshot(self):
        data = self.submit()
        job_id = data['job']['id']
        request = self.store.get_request(job_id)
        planning = Mock()
        planning.create_plan.return_value = ProductionPlan('FEASIBLE', request.task.product_card_id, 2, 0, ())
        service = PlanningJobService(planning, self.store)
        errors = []

        def work():
            try:
                # Complete only after SSE has actually subscribed to Redis.
                deadline = time.monotonic() + 5
                while not self.redis.pubsub_numsub(self.store.channel(job_id))[0][1]:
                    if time.monotonic() > deadline:
                        raise AssertionError('SSE did not subscribe')
                    time.sleep(.01)
                process_message(self.store, service, self.store.receive('test-worker'))
            except Exception as error:
                errors.append(error)
                job = self.store.get(job_id)
                if job.status == JobStatus.PENDING:
                    self.store.save(job.start(datetime.now(timezone.utc)).fail(str(error), datetime.now(timezone.utc)))

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        response = self.client.get(data['eventsUrl'])
        thread.join(timeout=10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/event-stream', response.headers['content-type'])
        self.assertIn('event: job', response.text)
        self.assertIn('"status": "completed"', response.text)
        self.assertEqual(self.store.get(job_id).result.status, 'FEASIBLE')
        self.assertEqual(self.redis.xpending(self.store.stream, self.store.group)['pending'], 0)
        # Pub/Sub does not replay; persisted snapshots do, even on a late connection.
        replay = self.client.get(data['eventsUrl'])
        self.assertIn('"status": "completed"', replay.text)
        self.assertEqual(replay.text.count('event: job'), 1)

    def test_failed_job_is_persisted_and_delivered_over_sse(self):
        data = self.submit()
        planning = Mock()
        planning.create_plan.side_effect = ValueError('План не помещается в смену')
        process_message(self.store, PlanningJobService(planning, self.store), self.store.receive('worker'))
        result = self.client.get(data['resultUrl']).json()
        self.assertEqual(result['job']['status'], 'failed')
        self.assertIsNotNone(result['job']['finishedAt'])
        self.assertIsNone(result['status'])
        self.assertIn('План не помещается', self.client.get(data['eventsUrl']).text)

    def test_interrupted_delivery_is_recovered_and_not_executed_twice(self):
        data = self.submit()
        original = self.store.receive('old-worker')
        job = self.store.get(data['job']['id']).start(datetime.now(timezone.utc))
        self.store.save(job)
        recovered = self.store.receive('new-worker', idle_ms=0)
        self.assertEqual(original[0], recovered[0])
        planning = Mock()
        process_message(self.store, PlanningJobService(planning, self.store), recovered)
        planning.create_plan.assert_not_called()
        self.assertEqual(self.store.get(job.id).status, JobStatus.FAILED)
        self.assertEqual(self.redis.xpending(self.store.stream, self.store.group)['pending'], 0)

    def test_full_department_comparison_survives_redis_and_sse(self):
        from types import SimpleNamespace
        from test_department_planning import request_for_test
        from planner.application import ProductionPlanningService
        from planner.infrastructure.cp_sat_planner import CpSatProductionPlanner
        with patch('planner.web.generate_test_data', return_value=SimpleNamespace(request=request_for_test())):
            response = self.client.post('/api/jobs', json={'count': 2, 'planning_day': '2026-10-05', 'horizon_days': 1})
        self.assertEqual(response.status_code, 202)
        data = response.json()
        pending = self.client.get(data['resultUrl']).json()
        self.assertTrue(pending['comparisonMode'])
        self.assertEqual(len(pending['departmentComparison']), 2)
        self.assertEqual(pending['completedDepartments'], 0)
        service = PlanningJobService(ProductionPlanningService(CpSatProductionPlanner(max_time_sec=2)), self.store)
        process_message(self.store, service, self.store.receive('comparison-worker'))
        final = self.client.get(data['resultUrl']).json()
        self.assertEqual(final['job']['status'], 'completed')
        self.assertEqual(final['completedDepartments'], 2)
        for scenario in final['departmentComparison']:
            self.assertEqual(len(scenario['operations']), 4)
            self.assertEqual({operation['departmentId'] for operation in scenario['operations']}, {scenario['departmentId']})
        stream = self.client.get(data['eventsUrl'])
        self.assertIn('"completedDepartments": 2', stream.text)
        self.assertEqual([item['elapsedSec'] for item in final['departmentComparison']], [400, 500])
