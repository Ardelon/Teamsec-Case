from datetime import date, timezone
from decimal import Decimal

from django.db.models import Max

from apps.etl.models import CreditRecord

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


def _serialize_date(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _serialize_decimal(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def build_credit_row_payload(credit: CreditRecord) -> dict:
    return {
        "loan_account_number": credit.loan_account_number,
        "customer_id": credit.customer_id,
        "customer_type": credit.customer_type,
        "loan_status_code": credit.loan_status_code,
        "days_past_due": credit.days_past_due,
        "final_maturity_date": _serialize_date(credit.final_maturity_date),
        "total_installment_count": credit.total_installment_count,
        "outstanding_installment_count": credit.outstanding_installment_count,
        "paid_installment_count": credit.paid_installment_count,
        "first_payment_date": _serialize_date(credit.first_payment_date),
        "original_loan_amount": _serialize_decimal(credit.original_loan_amount),
        "outstanding_principal_balance": _serialize_decimal(credit.outstanding_principal_balance),
        "nominal_interest_rate": _serialize_decimal(credit.nominal_interest_rate),
        "loan_start_date": _serialize_date(credit.loan_start_date),
        "loan_closing_date": _serialize_date(credit.loan_closing_date),
        "internal_rating": credit.internal_rating,
        "external_rating": credit.external_rating,
    }


def get_data_snapshot(
    tenant_id: str,
    loan_type: str,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> dict:
    page = max(page, 1)
    page_size = min(max(page_size, 1), MAX_PAGE_SIZE)

    base_qs = CreditRecord.objects.filter(tenant_id=tenant_id, loan_type=loan_type)
    total_count = base_qs.count()
    total_pages = (total_count + page_size - 1) // page_size if total_count else 0
    if total_pages and page > total_pages:
        page = total_pages

    latest_snapshot = base_qs.aggregate(latest=Max("snapshot_at"))["latest"]
    extraction_date = (
        latest_snapshot.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        if latest_snapshot
        else None
    )

    offset = (page - 1) * page_size
    credits = base_qs.order_by("loan_account_number")[offset : offset + page_size]

    return {
        "tenant_id": tenant_id,
        "loan_type": loan_type,
        "extraction_date": extraction_date,
        "credits": [build_credit_row_payload(c) for c in credits],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_count": total_count,
            "total_pages": total_pages,
            "has_previous": page > 1,
            "has_next": total_pages > 0 and page < total_pages,
        },
    }
