from rest_framework import serializers

from bank.constants import (
    CREDIT_DATA_TYPE,
    CREDITS_FILENAME,
    LOAN_TYPE_CHOICES,
    PAYMENT_PLAN_DATA_TYPE,
    PAYMENTS_FILENAME,
    TENANT_CHOICES,
)


class UploadSerializer(serializers.Serializer):
    tenant_id = serializers.ChoiceField(choices=TENANT_CHOICES)
    loan_type = serializers.ChoiceField(choices=LOAN_TYPE_CHOICES)
    credit_file = serializers.FileField()
    payment_plan_file = serializers.FileField()


def build_upload_response(tenant_id: str, loan_type: str, credits_size: int, payments_size: int, timestamp: str) -> dict:
    return {
        "status": "success",
        "tenant_id": tenant_id,
        "loan_type": loan_type,
        "uploaded_files": [
            {
                "type": CREDIT_DATA_TYPE,
                "filename": CREDITS_FILENAME,
                "size_bytes": credits_size,
            },
            {
                "type": PAYMENT_PLAN_DATA_TYPE,
                "filename": PAYMENTS_FILENAME,
                "size_bytes": payments_size,
            },
        ],
        "timestamp": timestamp,
    }
