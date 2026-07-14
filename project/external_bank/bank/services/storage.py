from pathlib import Path

from django.conf import settings

from bank.constants import CREDITS_FILENAME, LOAN_TYPES, PAYMENTS_FILENAME, TENANT_IDS


def portfolio_dir(tenant_id: str, loan_type: str) -> Path:
    return settings.STORAGE_ROOT / tenant_id / loan_type


def credits_path(tenant_id: str, loan_type: str) -> Path:
    return portfolio_dir(tenant_id, loan_type) / CREDITS_FILENAME


def payments_path(tenant_id: str, loan_type: str) -> Path:
    return portfolio_dir(tenant_id, loan_type) / PAYMENTS_FILENAME


def save_upload_files(tenant_id: str, loan_type: str, credit_file, payment_plan_file) -> tuple[int, int]:
    target_dir = portfolio_dir(tenant_id, loan_type)
    target_dir.mkdir(parents=True, exist_ok=True)

    credits_target = credits_path(tenant_id, loan_type)
    payments_target = payments_path(tenant_id, loan_type)

    credits_size = _write_uploaded_file(credit_file, credits_target)
    payments_size = _write_uploaded_file(payment_plan_file, payments_target)
    return credits_size, payments_size


def _write_uploaded_file(uploaded_file, destination: Path) -> int:
    size = 0
    with destination.open("wb") as handle:
        for chunk in uploaded_file.chunks():
            handle.write(chunk)
            size += len(chunk)
    return size


def list_portfolios() -> list[dict]:
    portfolios = []
    for tenant_id in TENANT_IDS:
        for loan_type in LOAN_TYPES:
            credits = credits_path(tenant_id, loan_type)
            payments = payments_path(tenant_id, loan_type)
            has_credits = credits.exists()
            has_payments = payments.exists()
            if not has_credits and not has_payments:
                continue
            portfolios.append(
                {
                    "tenant_id": tenant_id,
                    "loan_type": loan_type,
                    "has_credits": has_credits,
                    "has_payments": has_payments,
                    "credits_size_bytes": credits.stat().st_size if has_credits else 0,
                    "payments_size_bytes": payments.stat().st_size if has_payments else 0,
                }
            )
    return portfolios


def validate_tenant_id(tenant_id: str) -> str | None:
    if tenant_id not in TENANT_IDS:
        return f"Invalid tenant_id. Must be one of: {', '.join(TENANT_IDS)}"
    return None


def validate_loan_type(loan_type: str) -> str | None:
    if loan_type not in LOAN_TYPES:
        return f"Invalid loan_type. Must be one of: {', '.join(LOAN_TYPES)}"
    return None
