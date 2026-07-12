import os
import sys
import tempfile
from pathlib import Path

EXTERNAL_BANK_ROOT = Path(__file__).resolve().parents[1] / "external_bank"
sys.path.insert(0, str(EXTERNAL_BANK_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bank.settings")

import django

django.setup()

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient


class ExternalBankAPITestCase(TestCase):
    def setUp(self):
        self.temp_storage = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(
            STORAGE_ROOT=Path(self.temp_storage.name),
            STREAM_MULTIPLIER=3,
            STREAM_SIZE_LIMIT_BYTES=1024 * 1024,
        )
        self.settings_override.enable()
        self.client = APIClient()
        self.credit_content = b"loan_id;amount\nL001;1000.00\nL002;2000.00\n"
        self.payment_content = b"loan_id;due_date;amount\nL001;2026-01-01;100.00\n"

    def tearDown(self):
        self.settings_override.disable()
        self.temp_storage.cleanup()

    def _upload(self, tenant_id="BANK001", loan_type="RETAIL"):
        return self.client.post(
            "/api/bank/upload",
            {
                "tenant_id": tenant_id,
                "loan_type": loan_type,
                "credit_file": SimpleUploadedFile("credits.csv", self.credit_content, "text/csv"),
                "payment_plan_file": SimpleUploadedFile("payments.csv", self.payment_content, "text/csv"),
            },
            format="multipart",
        )

    def test_upload_returns_201_with_expected_schema(self):
        response = self._upload()
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["tenant_id"], "BANK001")
        self.assertEqual(data["loan_type"], "RETAIL")
        self.assertEqual(len(data["uploaded_files"]), 2)
        self.assertEqual(data["uploaded_files"][0]["type"], "credit_data")
        self.assertEqual(data["uploaded_files"][0]["filename"], "credits.csv")
        self.assertEqual(data["uploaded_files"][0]["size_bytes"], len(self.credit_content))
        self.assertEqual(data["uploaded_files"][1]["type"], "payment_plan_data")
        self.assertEqual(data["uploaded_files"][1]["filename"], "payments.csv")
        self.assertEqual(data["uploaded_files"][1]["size_bytes"], len(self.payment_content))
        self.assertTrue(data["timestamp"].endswith("Z"))

    def test_upload_rejects_invalid_tenant_id(self):
        response = self._upload(tenant_id="INVALID")
        self.assertEqual(response.status_code, 400)
        self.assertIn("tenant_id", response.json())

    def test_upload_rejects_missing_files(self):
        response = self.client.post(
            "/api/bank/upload",
            {"tenant_id": "BANK001", "loan_type": "RETAIL"},
            format="multipart",
        )
        self.assertEqual(response.status_code, 400)

    def test_export_returns_404_without_upload(self):
        response = self.client.get(
            "/api/bank/export/credits",
            {"tenant_id": "BANK002", "loan_type": "COMMERCIAL"},
        )
        self.assertEqual(response.status_code, 404)

    def test_export_credits_without_multiply(self):
        self._upload()
        response = self.client.get(
            "/api/bank/export/credits",
            {"tenant_id": "BANK001", "loan_type": "RETAIL"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertEqual(b"".join(response.streaming_content), self.credit_content)

    def test_export_payments_without_multiply(self):
        self._upload()
        response = self.client.get(
            "/api/bank/export/payments",
            {"tenant_id": "BANK001", "loan_type": "RETAIL"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), self.payment_content)

    def test_export_with_multiply_produces_larger_output(self):
        self._upload()
        response = self.client.get(
            "/api/bank/export/credits",
            {"tenant_id": "BANK001", "loan_type": "RETAIL", "multiply": "true"},
        )
        self.assertEqual(response.status_code, 200)
        content = b"".join(response.streaming_content)
        self.assertGreater(len(content), len(self.credit_content))

    def test_health_endpoint(self):
        response = self.client.get("/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")


if __name__ == "__main__":
    import unittest

    unittest.main()
