from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.utils import timezone as dj_timezone

from apps.etl.models import CreditRecord, PaymentInstallment


def _parse_date(value: str | None) -> date | None:
    if not value or not str(value).strip():
        return None
    raw = str(value).strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parse_decimal(value: str | None) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def _parse_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _serialize_date(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _serialize_decimal(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def build_credit_payload(credit: CreditRecord) -> dict:
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
        "total_interest_amount": _serialize_decimal(credit.total_interest_amount),
        "kkdf_rate": _serialize_decimal(credit.kkdf_rate),
        "kkdf_amount": _serialize_decimal(credit.kkdf_amount),
        "bsmv_rate": _serialize_decimal(credit.bsmv_rate),
        "bsmv_amount": _serialize_decimal(credit.bsmv_amount),
        "grace_period_months": credit.grace_period_months,
        "installment_frequency": credit.installment_frequency,
        "loan_start_date": _serialize_date(credit.loan_start_date),
        "loan_closing_date": _serialize_date(credit.loan_closing_date),
        "internal_rating": credit.internal_rating,
        "external_rating": credit.external_rating,
        "commercial_specific_attributes": credit.commercial_specific_attributes or {},
        "retail_specific_attributes": credit.retail_specific_attributes or {},
        "payment_schedule": [
            {
                "installment_number": p.installment_number,
                "actual_payment_date": _serialize_date(p.actual_payment_date),
                "scheduled_payment_date": _serialize_date(p.scheduled_payment_date),
                "installment_amount": _serialize_decimal(p.installment_amount),
                "principal_component": _serialize_decimal(p.principal_component),
                "interest_component": _serialize_decimal(p.interest_component),
                "kkdf_component": _serialize_decimal(p.kkdf_component),
                "bsmv_component": _serialize_decimal(p.bsmv_component),
                "installment_status": p.installment_status,
                "remaining_principal": _serialize_decimal(p.remaining_principal),
                "remaining_interest": _serialize_decimal(p.remaining_interest),
                "remaining_kkdf": _serialize_decimal(p.remaining_kkdf),
                "remaining_bsmv": _serialize_decimal(p.remaining_bsmv),
            }
            for p in credit.payment_schedule.all()
        ],
    }


def get_data_snapshot(tenant_id: str, loan_type: str) -> dict:
    credits = (
        CreditRecord.objects.filter(tenant_id=tenant_id, loan_type=loan_type)
        .prefetch_related("payment_schedule")
        .order_by("loan_account_number")
    )
    latest = credits.order_by("-snapshot_at").first()
    extraction_date = (
        latest.snapshot_at.astimezone(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        if latest
        else None
    )
    return {
        "tenant_id": tenant_id,
        "loan_type": loan_type,
        "extraction_date": extraction_date,
        "credits": [build_credit_payload(c) for c in credits],
    }


def credit_from_csv_row(tenant_id: str, loan_type: str, row: dict) -> CreditRecord:
    loan_type_upper = loan_type.upper()
    retail_attrs = {}
    commercial_attrs = {}

    if loan_type_upper == "RETAIL":
        retail_attrs = {
            "insurance_included": row.get("insurance_included", ""),
            "customer_district_code": row.get("customer_district_code", ""),
            "customer_province_code": row.get("customer_region_code", row.get("customer_province_code", "")),
        }
    else:
        commercial_attrs = {
            "loan_product_type": _parse_int(row.get("loan_product_type")),
            "loan_status_flag": row.get("loan_status_flag", ""),
            "customer_region_code": row.get("customer_region_code", ""),
            "sector_code": _parse_int(row.get("sector_code")),
            "internal_credit_rating": _parse_int(row.get("internal_credit_rating")),
            "default_probability": _serialize_decimal(_parse_decimal(row.get("default_probability"))),
            "risk_class": _parse_int(row.get("risk_class")),
            "customer_segment": _parse_int(row.get("customer_segment")),
        }

    return CreditRecord(
        tenant_id=tenant_id,
        loan_type=loan_type_upper,
        loan_account_number=row.get("loan_account_number", ""),
        customer_id=row.get("customer_id", ""),
        customer_type=row.get("customer_type", ""),
        loan_status_code=row.get("loan_status_code", ""),
        days_past_due=_parse_int(row.get("days_past_due")),
        final_maturity_date=_parse_date(row.get("final_maturity_date")),
        total_installment_count=_parse_int(row.get("total_installment_count")),
        outstanding_installment_count=_parse_int(row.get("outstanding_installment_count")),
        paid_installment_count=_parse_int(row.get("paid_installment_count")),
        first_payment_date=_parse_date(row.get("first_payment_date")),
        original_loan_amount=_parse_decimal(row.get("original_loan_amount")),
        outstanding_principal_balance=_parse_decimal(row.get("outstanding_principal_balance")),
        nominal_interest_rate=_parse_decimal(row.get("nominal_interest_rate")),
        total_interest_amount=_parse_decimal(row.get("total_interest_amount")),
        kkdf_rate=_parse_decimal(row.get("kkdf_rate")),
        kkdf_amount=_parse_decimal(row.get("kkdf_amount")),
        bsmv_rate=_parse_decimal(row.get("bsmv_rate")),
        bsmv_amount=_parse_decimal(row.get("bsmv_amount")),
        grace_period_months=_parse_int(row.get("grace_period_months")),
        installment_frequency=_parse_int(row.get("installment_frequency")),
        loan_start_date=_parse_date(row.get("loan_start_date")),
        loan_closing_date=_parse_date(row.get("loan_closing_date")),
        internal_rating=_parse_int(row.get("internal_rating")),
        external_rating=_parse_int(row.get("external_rating")),
        retail_specific_attributes=retail_attrs,
        commercial_specific_attributes=commercial_attrs,
        snapshot_at=dj_timezone.now(),
    )


def payment_from_csv_row(credit: CreditRecord, row: dict) -> PaymentInstallment:
    return PaymentInstallment(
        credit=credit,
        installment_number=_parse_int(row.get("installment_number")) or 0,
        actual_payment_date=_parse_date(row.get("actual_payment_date")),
        scheduled_payment_date=_parse_date(row.get("scheduled_payment_date")),
        installment_amount=_parse_decimal(row.get("installment_amount")),
        principal_component=_parse_decimal(row.get("principal_component")),
        interest_component=_parse_decimal(row.get("interest_component")),
        kkdf_component=_parse_decimal(row.get("kkdf_component")),
        bsmv_component=_parse_decimal(row.get("bsmv_component")),
        installment_status=row.get("installment_status", ""),
        remaining_principal=_parse_decimal(row.get("remaining_principal")),
        remaining_interest=_parse_decimal(row.get("remaining_interest")),
        remaining_kkdf=_parse_decimal(row.get("remaining_kkdf")),
        remaining_bsmv=_parse_decimal(row.get("remaining_bsmv")),
    )
