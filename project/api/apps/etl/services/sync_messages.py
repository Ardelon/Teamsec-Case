import re


def humanize_sync_error(message: str, tenant_id: str = "", loan_type: str = "") -> dict:
    text = (message or "").strip()
    tenant = tenant_id or "your bank"
    loan = loan_type or "the selected loan type"

    if "cancelled by user" in text.lower() or text == "Sync cancelled by user":
        return {
            "title": "Sync cancelled",
            "message": "The sync job was cancelled before it finished.",
            "hint": "You can start a new sync whenever you want.",
            "code": "CANCELLED",
        }

    if "No credits.csv found" in text:
        return {
            "title": "No credit data to sync",
            "message": f"{tenant} has no {loan} credit portfolio uploaded yet.",
            "hint": "Choose a loan type that has data (e.g. RETAIL for BANK001) or upload files via the external bank API.",
            "code": "NO_SOURCE_DATA",
        }

    if "No payments.csv found" in text:
        return {
            "title": "No payment data to sync",
            "message": f"{tenant} has no {loan} payment schedule uploaded yet.",
            "hint": "Upload both credits.csv and payments.csv for this tenant and loan type before syncing.",
            "code": "NO_SOURCE_DATA",
        }

    if "404" in text and "export/" in text:
        return {
            "title": "No data available to sync",
            "message": f"The external bank returned no files for {tenant} / {loan}.",
            "hint": "Verify the portfolio exists for this tenant and loan type, then try again.",
            "code": "NO_SOURCE_DATA",
        }

    if text.startswith("HTTP error:") and "400" in text:
        return {
            "title": "Invalid sync request",
            "message": "The bank rejected the export request.",
            "hint": "Check tenant and loan type values, then try again.",
            "code": "BAD_REQUEST",
        }

    if "Database error:" in text:
        return {
            "title": "Could not save synced data",
            "message": "Data was fetched but could not be written to the warehouse.",
            "hint": re.sub(r"^Database error:\s*", "", text) or None,
            "code": "DATABASE_ERROR",
        }

    return {
        "title": "Sync failed",
        "message": re.sub(r"^(HTTP error:|Database error:)\s*", "", text) or "An unexpected error occurred during sync.",
        "hint": None,
        "code": "PIPELINE_ERROR",
    }
