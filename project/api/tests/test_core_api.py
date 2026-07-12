from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.core.models import OperatorProfile
from apps.core.services.redis_lock import acquire_sync_lock, get_redis_client, release_sync_lock
from apps.etl.models import ETLJob
from apps.etl.tasks import run_etl_pipeline


class _MockMetrics(SimpleNamespace):
    pass


class _MockPipelineResult(SimpleNamespace):
    pass


def _mock_pipeline_result():
    return _MockPipelineResult(
        success=True,
        processed_rows_count=2,
        execution_duration_seconds=0.1,
        metrics=_MockMetrics(total_credits_ingested=1, total_payments_ingested=1),
        error_logs=[],
    )


class CoreAPITestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        get_redis_client().delete("lock:BANK001:RETAIL", "lock:BANK001:COMMERCIAL")
        self.user = User.objects.create_user(username="operator_admin", password="secure_cleartext_password")
        OperatorProfile.objects.create(user=self.user, tenant_id="BANK001")
        login = self.client.post(
            "/api/auth/login",
            {"username": "operator_admin", "password": "secure_cleartext_password", "tenant_id": "BANK001"},
            format="json",
        )
        self.token = login.data["token"]
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {self.token}"}

    def tearDown(self):
        get_redis_client().delete("lock:BANK001:RETAIL", "lock:BANK001:COMMERCIAL")

    def test_login_success(self):
        response = self.client.post(
            "/api/auth/login",
            {"username": "operator_admin", "password": "secure_cleartext_password", "tenant_id": "BANK001"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("token", response.data)
        self.assertEqual(response.data["tenant_id"], "BANK001")

    def test_login_invalid_credentials(self):
        response = self.client.post(
            "/api/auth/login",
            {"username": "operator_admin", "password": "wrong", "tenant_id": "BANK001"},
            format="json",
        )
        self.assertEqual(response.status_code, 401)

    def test_sync_requires_auth(self):
        response = self.client.post("/api/sync", {"loan_type": "RETAIL"}, format="json")
        self.assertEqual(response.status_code, 403)

    @patch("apps.etl.views.run_etl_pipeline.delay")
    def test_sync_queues_job(self, mock_delay):
        response = self.client.post("/api/sync", {"loan_type": "RETAIL"}, format="json", **self.auth)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data["status"], "QUEUED")
        self.assertTrue(response.data["job_id"].startswith("job_"))
        mock_delay.assert_called_once()
        release_sync_lock(get_redis_client(), "BANK001", "RETAIL", response.data["job_id"])

    @patch("apps.etl.views.run_etl_pipeline.delay")
    def test_sync_lock_conflict(self, mock_delay):
        redis_client = get_redis_client()
        acquire_sync_lock(redis_client, "BANK001", "RETAIL", "job_existing")
        response = self.client.post("/api/sync", {"loan_type": "RETAIL"}, format="json", **self.auth)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["active_job_id"], "job_existing")
        release_sync_lock(redis_client, "BANK001", "RETAIL", "job_existing")

    def test_tenant_mismatch_forbidden(self):
        response = self.client.get("/api/data?loan_type=RETAIL&tenant_id=BANK002", **self.auth)
        self.assertEqual(response.status_code, 403)

    def test_sync_status_returns_progress(self):
        job = ETLJob.objects.create(
            job_id="job_test_status",
            tenant_id="BANK001",
            loan_type="RETAIL",
            status=ETLJob.STATUS_PROCESSING,
            progress_percentage=48,
            processed_rows=100,
        )
        response = self.client.get(f"/api/sync/status/{job.job_id}", **self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["processed_rows"], 100)
        self.assertEqual(response.data["progress_percentage"], 48)

    def test_data_snapshot_empty(self):
        response = self.client.get("/api/data?loan_type=RETAIL", **self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["credits"], [])

    def test_profiling_empty(self):
        response = self.client.get("/api/profiling?loan_type=RETAIL", **self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total_records_processed"], 0)
        self.assertIn("charts", response.data)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    @patch("adapter_core.execute_etl_pipeline", return_value=_mock_pipeline_result())
    def test_pipeline_completes_and_releases_lock(self, _mock_rust):
        redis_client = get_redis_client()
        job_id = "job_pipeline_test"
        acquire_sync_lock(redis_client, "BANK001", "RETAIL", job_id)
        ETLJob.objects.create(job_id=job_id, tenant_id="BANK001", loan_type="RETAIL", status=ETLJob.STATUS_QUEUED)
        run_etl_pipeline(job_id, "BANK001", "RETAIL")
        job = ETLJob.objects.get(job_id=job_id)
        self.assertEqual(job.status, ETLJob.STATUS_COMPLETED)
        self.assertEqual(job.processed_rows, 2)
        self.assertIsNone(get_redis_client().get("lock:BANK001:RETAIL"))
        self.assertIsNotNone(get_redis_client().get(f"job:state:{job_id}"))
