import uuid

import datetime

from django.conf import settings
from rest_framework import serializers

from apps.etl.models import ETLJob


class SyncRequestSerializer(serializers.Serializer):
    loan_type = serializers.ChoiceField(choices=list(settings.LOAN_TYPES))
    tenant_id = serializers.CharField(max_length=64, required=False)


class SyncResponseSerializer(serializers.ModelSerializer):
    created_at = serializers.SerializerMethodField()

    class Meta:
        model = ETLJob
        fields = ["job_id", "tenant_id", "loan_type", "status", "created_at"]

    def get_created_at(self, obj):
        return obj.created_at.astimezone(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


class JobStatusSerializer(serializers.ModelSerializer):
    started_at = serializers.SerializerMethodField()
    completed_at = serializers.SerializerMethodField()
    records_processed = serializers.IntegerField(source="processed_rows")

    class Meta:
        model = ETLJob
        fields = [
            "job_id",
            "tenant_id",
            "loan_type",
            "status",
            "progress_percentage",
            "processed_rows",
            "records_processed",
            "started_at",
            "completed_at",
            "errors",
            "validation_summary",
        ]

    def get_started_at(self, obj):
        if not obj.started_at:
            return None
        return obj.started_at.astimezone(datetime.timezone.utc).isoformat().replace("+00:00", "Z")

    def get_completed_at(self, obj):
        if not obj.completed_at:
            return None
        return obj.completed_at.astimezone(datetime.timezone.utc).isoformat().replace("+00:00", "Z")

    def to_representation(self, instance):
        data = super().to_representation(instance)
        errors = []
        for err in instance.errors or []:
            errors.append(
                {
                    "row_number": err.get("row_number"),
                    "field": err.get("field"),
                    "error_type": err.get("error_type"),
                    "message": err.get("message", err.get("error_message", "")),
                }
            )
        data["errors"] = errors
        return data


def new_job_id() -> str:
    return f"job_{uuid.uuid4()}"
