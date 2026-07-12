import datetime
from collections import Counter
from decimal import Decimal

from django.db.models import Avg, Max, Min, StdDev
from django.utils import timezone as dj_timezone

from apps.etl.models import CreditRecord


NUMERICAL_FIELDS = (
    "original_loan_amount",
    "outstanding_principal_balance",
    "nominal_interest_rate",
)

CATEGORICAL_FIELDS = (
    "loan_status_code",
    "customer_type",
)

NULL_RATIO_FIELDS = (
    "loan_closing_date",
    "days_past_due",
    "original_loan_amount",
)


def _null_ratio(qs, field_name: str, total: int) -> float:
    if total == 0:
        return 0.0
    null_count = qs.filter(**{f"{field_name}__isnull": True}).count()
    return round(null_count / total, 4)


def _numerical_stats(qs, field_name: str, total: int) -> dict:
    agg = qs.aggregate(
        min_val=Min(field_name),
        max_val=Max(field_name),
        avg_val=Avg(field_name),
        std_val=StdDev(field_name),
    )
    return {
        "min": float(agg["min_val"]) if agg["min_val"] is not None else 0.0,
        "max": float(agg["max_val"]) if agg["max_val"] is not None else 0.0,
        "avg": float(agg["avg_val"]) if agg["avg_val"] is not None else 0.0,
        "stddev": float(agg["std_val"]) if agg["std_val"] is not None else 0.0,
        "null_ratio": _null_ratio(qs, field_name, total),
    }


def _categorical_stats(qs, field_name: str, total: int) -> dict:
    values = list(qs.exclude(**{f"{field_name}__isnull": True}).values_list(field_name, flat=True))
    counter = Counter(values)
    most_frequent = counter.most_common(1)[0][0] if counter else ""
    return {
        "unique_values_count": len(counter),
        "most_frequent_value": most_frequent,
        "null_ratio": _null_ratio(qs, field_name, total),
    }


def _categorical_distribution(qs, field_name: str) -> list[dict]:
    values = list(qs.exclude(**{f"{field_name}__isnull": True}).values_list(field_name, flat=True))
    counter = Counter(values)
    return [{"value": value, "count": count} for value, count in counter.most_common()]


def build_profiling_payload(tenant_id: str, loan_type: str) -> dict:
    qs = CreditRecord.objects.filter(tenant_id=tenant_id, loan_type=loan_type)
    total = qs.count()
    generated_at = dj_timezone.now().astimezone(datetime.timezone.utc).isoformat().replace("+00:00", "Z")

    numerical_fields = {
        field: _numerical_stats(qs, field, total) for field in NUMERICAL_FIELDS
    }
    categorical_fields = {
        field: _categorical_stats(qs, field, total) for field in CATEGORICAL_FIELDS
    }

    null_fields_distribution = [
        {"field": field, "ratio": _null_ratio(qs, field, total)}
        for field in NULL_RATIO_FIELDS
    ]

    categorical_distributions = {
        field: _categorical_distribution(qs, field) for field in CATEGORICAL_FIELDS
    }

    return {
        "tenant_id": tenant_id,
        "loan_type": loan_type,
        "generated_at": generated_at,
        "total_records_processed": total,
        "total_records": total,
        "numerical_fields": numerical_fields,
        "categorical_fields": categorical_fields,
        "metrics": {
            "numerical_columns": numerical_fields,
            "categorical_columns": categorical_fields,
        },
        "summary": {
            "total_records": total,
            "null_fields_distribution": null_fields_distribution,
        },
        "charts": {
            "categorical_distributions": categorical_distributions,
        },
    }
