import datetime

from django.db.models import Avg, Count, Max, Min, Q, StdDev
from django.utils import timezone as dj_timezone

from apps.etl.models import CreditRecord, PaymentInstallment

# Aligned with public warehouse credit DTO (apps.etl.services.warehouse).
NUMERICAL_FIELDS = (
    "days_past_due",
    "total_installment_count",
    "outstanding_installment_count",
    "paid_installment_count",
    "original_loan_amount",
    "outstanding_principal_balance",
    "nominal_interest_rate",
    "internal_rating",
    "external_rating",
)

CATEGORICAL_FIELDS = (
    "customer_type",
    "loan_status_code",
)

NULLABLE_CHAR_FIELDS = frozenset(
    {
        "customer_id",
        "customer_type",
        "loan_status_code",
        "loan_account_number",
    }
)

NULL_RATIO_FIELDS = (
    "loan_account_number",
    "customer_id",
    "customer_type",
    "loan_status_code",
    "days_past_due",
    "final_maturity_date",
    "total_installment_count",
    "outstanding_installment_count",
    "paid_installment_count",
    "first_payment_date",
    "original_loan_amount",
    "outstanding_principal_balance",
    "nominal_interest_rate",
    "loan_start_date",
    "loan_closing_date",
    "internal_rating",
    "external_rating",
)

PAYMENT_NUMERICAL_FIELDS = (
    "installment_amount",
    "principal_component",
    "interest_component",
    "remaining_principal",
)

PAYMENT_CATEGORICAL_FIELDS = ("installment_status",)

PAYMENT_NULL_RATIO_FIELDS = (
    "actual_payment_date",
    "scheduled_payment_date",
    "installment_amount",
    "principal_component",
    "interest_component",
    "installment_status",
    "remaining_principal",
)


def _to_float(value) -> float | None:
    if value is None:
        return None
    return float(value)


def _null_filter(field_name: str) -> Q:
    if field_name in NULLABLE_CHAR_FIELDS:
        return Q(**{f"{field_name}__isnull": True}) | Q(**{field_name: ""})
    return Q(**{f"{field_name}__isnull": True})


def _null_ratio(qs, field_name: str, total: int) -> float:
    if total == 0:
        return 0.0
    null_count = qs.filter(_null_filter(field_name)).count()
    return round(null_count / total, 4)


def _null_ratio_percent(qs, field_name: str, total: int) -> float:
    return round(_null_ratio(qs, field_name, total) * 100, 2)


def _numerical_stats(qs, field_name: str, total: int) -> dict:
    agg = qs.aggregate(
        min_val=Min(field_name),
        max_val=Max(field_name),
        avg_val=Avg(field_name),
        std_val=StdDev(field_name),
        non_null=Count(field_name),
    )
    return {
        "min": _to_float(agg["min_val"]) if agg["min_val"] is not None else None,
        "max": _to_float(agg["max_val"]) if agg["max_val"] is not None else None,
        "avg": round(_to_float(agg["avg_val"]), 4) if agg["avg_val"] is not None else None,
        "stddev": round(_to_float(agg["std_val"]), 4) if agg["std_val"] is not None else None,
        "non_null_count": agg["non_null"] or 0,
        "null_ratio": _null_ratio(qs, field_name, total),
        "null_ratio_percent": _null_ratio_percent(qs, field_name, total),
    }


def _categorical_stats(qs, field_name: str, total: int) -> dict:
    populated = qs.exclude(_null_filter(field_name))
    unique_values_count = populated.values(field_name).distinct().count()
    top = (
        populated.values(field_name)
        .annotate(cnt=Count("pk"))
        .order_by("-cnt", field_name)
        .first()
    )
    most_frequent_value = top[field_name] if top else None
    most_frequent_count = top["cnt"] if top else 0
    return {
        "unique_values_count": unique_values_count,
        "most_frequent_value": most_frequent_value if most_frequent_value is not None else "",
        "most_frequent_count": most_frequent_count,
        "null_ratio": _null_ratio(qs, field_name, total),
        "null_ratio_percent": _null_ratio_percent(qs, field_name, total),
    }


def _categorical_distribution(qs, field_name: str, limit: int = 15) -> list[dict]:
    populated = qs.exclude(_null_filter(field_name))
    rows = (
        populated.values(field_name)
        .annotate(count=Count("pk"))
        .order_by("-count", field_name)[:limit]
    )
    return [{"value": str(row[field_name]), "count": row["count"]} for row in rows]


def build_profiling_payload(tenant_id: str, loan_type: str) -> dict:
    credits = CreditRecord.objects.filter(tenant_id=tenant_id, loan_type=loan_type)
    total_credits = credits.count()
    payments = PaymentInstallment.objects.filter(
        credit__tenant_id=tenant_id,
        credit__loan_type=loan_type,
    )
    total_payments = payments.count()
    generated_at = dj_timezone.now().astimezone(datetime.timezone.utc).isoformat().replace("+00:00", "Z")

    numerical_fields = {
        field: _numerical_stats(credits, field, total_credits) for field in NUMERICAL_FIELDS
    }
    categorical_fields = {
        field: _categorical_stats(credits, field, total_credits) for field in CATEGORICAL_FIELDS
    }
    null_fields_distribution = [
        {
            "field": field,
            "ratio": _null_ratio(credits, field, total_credits),
            "ratio_percent": _null_ratio_percent(credits, field, total_credits),
        }
        for field in NULL_RATIO_FIELDS
    ]

    payment_numerical = {
        field: _numerical_stats(payments, field, total_payments) for field in PAYMENT_NUMERICAL_FIELDS
    }
    payment_categorical = {
        field: _categorical_stats(payments, field, total_payments) for field in PAYMENT_CATEGORICAL_FIELDS
    }
    payment_null_fields = [
        {
            "field": field,
            "ratio": _null_ratio(payments, field, total_payments),
            "ratio_percent": _null_ratio_percent(payments, field, total_payments),
        }
        for field in PAYMENT_NULL_RATIO_FIELDS
    ]

    categorical_distributions = {
        field: _categorical_distribution(credits, field) for field in CATEGORICAL_FIELDS
    }

    return {
        "tenant_id": tenant_id,
        "loan_type": loan_type,
        "generated_at": generated_at,
        "total_records_processed": total_credits,
        "total_records": total_credits,
        "total_payments": total_payments,
        "numerical_fields": numerical_fields,
        "categorical_fields": categorical_fields,
        "metrics": {
            "numerical_columns": numerical_fields,
            "categorical_columns": categorical_fields,
        },
        "summary": {
            "total_records": total_credits,
            "total_payments": total_payments,
            "null_fields_distribution": null_fields_distribution,
        },
        "payments": {
            "total_records": total_payments,
            "numerical_fields": payment_numerical,
            "categorical_fields": payment_categorical,
            "null_fields_distribution": payment_null_fields,
        },
        "charts": {
            "categorical_distributions": categorical_distributions,
            "null_fields_distribution": null_fields_distribution,
        },
    }
