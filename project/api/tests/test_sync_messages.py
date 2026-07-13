from django.test import SimpleTestCase

from apps.etl.services.sync_messages import humanize_sync_error


class SyncMessagesTests(SimpleTestCase):
    def test_no_credits_csv(self):
        result = humanize_sync_error(
            'HTTP error: HTTP 404 Not Found from http://externalbank:8080/api/bank/export/credits?tenant_id=BANK001&loan_type=COMMERCIAL: {"detail": "No credits.csv found for BANK001/COMMERCIAL"}',
            "BANK001",
            "COMMERCIAL",
        )
        self.assertEqual(result["code"], "NO_SOURCE_DATA")
        self.assertIn("BANK001", result["message"])
        self.assertIn("COMMERCIAL", result["message"])

    def test_generic_failure(self):
        result = humanize_sync_error("Something went wrong", "BANK002", "RETAIL")
        self.assertEqual(result["title"], "Sync failed")
