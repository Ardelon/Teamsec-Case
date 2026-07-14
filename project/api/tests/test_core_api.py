from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.core.models import OperatorProfile
from apps.core.services.redis_lock import acquire_sync_lock, get_active_job_id, get_redis_client, release_sync_lock
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
        mock_delay.return_value = SimpleNamespace(id="celery-task-1")
        response = self.client.post("/api/sync", {"loan_type": "RETAIL"}, format="json", **self.auth)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data["status"], "QUEUED")
        self.assertTrue(response.data["job_id"].startswith("job_"))
        mock_delay.assert_called_once()
        release_sync_lock(get_redis_client(), "BANK001", "RETAIL", response.data["job_id"])

    @patch("apps.etl.views.run_etl_pipeline.delay")
    def test_sync_lock_conflict(self, mock_delay):
        mock_delay.return_value = SimpleNamespace(id="celery-task-1")
        redis_client = get_redis_client()
        acquire_sync_lock(redis_client, "BANK001", "RETAIL", "job_existing")
        response = self.client.post("/api/sync", {"loan_type": "RETAIL"}, format="json", **self.auth)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["active_job_id"], "job_existing")
        release_sync_lock(redis_client, "BANK001", "RETAIL", "job_existing")

    @patch("apps.etl.views.run_etl_pipeline.delay")
    def test_sync_conflict_returns_active_job(self, mock_delay):
        mock_delay.return_value = SimpleNamespace(id="celery-task-1")
        redis_client = get_redis_client()
        job = ETLJob.objects.create(
            job_id="job_existing",
            tenant_id="BANK001",
            loan_type="RETAIL",
            status=ETLJob.STATUS_PROCESSING,
            progress_percentage=42,
            processed_rows=1200,
        )
        acquire_sync_lock(redis_client, "BANK001", "RETAIL", job.job_id)
        response = self.client.post("/api/sync", {"loan_type": "RETAIL"}, format="json", **self.auth)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["active_job_id"], job.job_id)
        self.assertEqual(response.data["active_job"]["progress_percentage"], 42)
        self.assertEqual(response.data["active_job"]["processed_rows"], 1200)
        mock_delay.assert_not_called()
        release_sync_lock(redis_client, "BANK001", "RETAIL", job.job_id)

    def test_active_sync_returns_running_job(self):
        redis_client = get_redis_client()
        job = ETLJob.objects.create(
            job_id="job_active",
            tenant_id="BANK001",
            loan_type="COMMERCIAL",
            status=ETLJob.STATUS_PROCESSING,
            progress_percentage=75,
            processed_rows=5000,
        )
        acquire_sync_lock(redis_client, "BANK001", "COMMERCIAL", job.job_id)
        response = self.client.get("/api/sync/active?loan_type=COMMERCIAL", **self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["active"])
        self.assertEqual(response.data["job_id"], job.job_id)
        self.assertEqual(response.data["progress_percentage"], 75)
        release_sync_lock(redis_client, "BANK001", "COMMERCIAL", job.job_id)

    def test_active_sync_returns_inactive_when_no_lock(self):
        response = self.client.get("/api/sync/active?loan_type=RETAIL", **self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["active"])

    @patch("apps.etl.views.run_etl_pipeline.delay")
    def test_sync_retail_and_commercial_in_parallel(self, mock_delay):
        mock_delay.return_value = SimpleNamespace(id="celery-task-1")
        retail = self.client.post("/api/sync", {"loan_type": "RETAIL"}, format="json", **self.auth)
        commercial = self.client.post("/api/sync", {"loan_type": "COMMERCIAL"}, format="json", **self.auth)
        self.assertEqual(retail.status_code, 202)
        self.assertEqual(commercial.status_code, 202)
        self.assertNotEqual(retail.data["job_id"], commercial.data["job_id"])
        self.assertEqual(mock_delay.call_count, 2)
        release_sync_lock(get_redis_client(), "BANK001", "RETAIL", retail.data["job_id"])
        release_sync_lock(get_redis_client(), "BANK001", "COMMERCIAL", commercial.data["job_id"])

    def test_cancel_sync_job(self):
        redis_client = get_redis_client()
        job = ETLJob.objects.create(
            job_id="job_to_cancel",
            tenant_id="BANK001",
            loan_type="RETAIL",
            status=ETLJob.STATUS_PROCESSING,
            progress_percentage=20,
        )
        acquire_sync_lock(redis_client, "BANK001", "RETAIL", job.job_id)
        with patch("apps.etl.services.cancel_sync.AsyncResult") as mock_result:
            mock_result.return_value.revoke = lambda *args, **kwargs: None
            response = self.client.post(f"/api/sync/cancel/{job.job_id}", **self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "CANCELLED")
        job.refresh_from_db()
        self.assertEqual(job.status, ETLJob.STATUS_CANCELLED)
        self.assertIsNone(get_active_job_id(redis_client, "BANK001", "RETAIL"))

    def test_cancel_completed_job_rejected(self):
        job = ETLJob.objects.create(
            job_id="job_done",
            tenant_id="BANK001",
            loan_type="RETAIL",
            status=ETLJob.STATUS_COMPLETED,
        )
        response = self.client.post(f"/api/sync/cancel/{job.job_id}", **self.auth)
        self.assertEqual(response.status_code, 400)

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
        self.assertEqual(response.data["pagination"]["total_count"], 0)

    def test_data_snapshot_pagination(self):
        from apps.etl.models import CreditRecord

        for index in range(1, 6):
            CreditRecord.objects.create(
                tenant_id="BANK001",
                loan_type="RETAIL",
                loan_account_number=f"LOAN_{index:03d}",
                customer_id=f"CUST_{index:03d}",
                loan_status_code="A",
            )

        response = self.client.get("/api/data?loan_type=RETAIL&page=1&page_size=2", **self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["credits"]), 2)
        self.assertEqual(response.data["pagination"]["total_count"], 5)
        self.assertEqual(response.data["pagination"]["total_pages"], 3)
        self.assertTrue(response.data["pagination"]["has_next"])
        self.assertFalse(response.data["pagination"]["has_previous"])

        response = self.client.get("/api/data?loan_type=RETAIL&page=3&page_size=2", **self.auth)
        self.assertEqual(len(response.data["credits"]), 1)
        self.assertFalse(response.data["pagination"]["has_next"])
        self.assertTrue(response.data["pagination"]["has_previous"])

    def test_profiling_empty(self):
        response = self.client.get("/api/profiling?loan_type=RETAIL", **self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total_records_processed"], 0)
        self.assertIn("charts", response.data)
        self.assertIn("numerical_fields", response.data)
        self.assertIn("categorical_fields", response.data)
        self.assertIn("null_fields_distribution", response.data["summary"])

    def test_profiling_with_records(self):
        from apps.etl.models import CreditRecord, PaymentInstallment

        credit = CreditRecord.objects.create(
            tenant_id="BANK001",
            loan_type="RETAIL",
            loan_account_number="LOAN_P1",
            customer_type="V",
            loan_status_code="A",
            original_loan_amount="1000.00",
            outstanding_principal_balance="500.00",
            nominal_interest_rate="1.25",
            days_past_due=0,
        )
        CreditRecord.objects.create(
            tenant_id="BANK001",
            loan_type="RETAIL",
            loan_account_number="LOAN_P2",
            customer_type="V",
            loan_status_code="K",
            original_loan_amount="3000.00",
            outstanding_principal_balance=None,
            nominal_interest_rate="2.50",
            days_past_due=None,
        )
        PaymentInstallment.objects.create(
            credit=credit,
            installment_number=1,
            installment_amount="100.00",
            principal_component="80.00",
            installment_status="K",
        )

        response = self.client.get("/api/profiling?loan_type=RETAIL", **self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total_records"], 2)
        self.assertEqual(response.data["total_payments"], 1)

        amount = response.data["numerical_fields"]["original_loan_amount"]
        self.assertEqual(amount["min"], 1000.0)
        self.assertEqual(amount["max"], 3000.0)
        self.assertEqual(amount["avg"], 2000.0)
        self.assertIsNotNone(amount["stddev"])

        status = response.data["categorical_fields"]["loan_status_code"]
        self.assertEqual(status["unique_values_count"], 2)
        self.assertIn(status["most_frequent_value"], {"A", "K"})

        null_map = {
            item["field"]: item["ratio"]
            for item in response.data["summary"]["null_fields_distribution"]
        }
        self.assertEqual(null_map["days_past_due"], 0.5)
        self.assertEqual(null_map["outstanding_principal_balance"], 0.5)
        self.assertEqual(
            response.data["payments"]["numerical_fields"]["installment_amount"]["avg"],
            100.0,
        )

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
