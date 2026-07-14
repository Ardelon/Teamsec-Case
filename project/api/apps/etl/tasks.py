import json
from datetime import timezone

from celery import shared_task
from django.conf import settings
from django.utils import timezone as dj_timezone

from apps.core.services.redis_lock import get_redis_client, release_sync_lock
from apps.etl.models import ETLJob
from apps.etl.services.cancel_sync import clear_cancel_flags, is_cancel_requested


def _database_url() -> str:
    db = settings.DATABASES["default"]
    return (
        f"postgres://{db['USER']}:{db['PASSWORD']}"
        f"@{db['HOST']}:{db['PORT']}/{db['NAME']}"
    )


def _bank_urls(tenant_id: str, loan_type: str) -> tuple[str, str]:
    base = settings.EXTERNAL_BANK_URL.rstrip("/")
    query = f"tenant_id={tenant_id}&loan_type={loan_type}"
    credits_url = f"{base}/api/bank/export/credits?{query}"
    payments_url = f"{base}/api/bank/export/payments?{query}"
    return credits_url, payments_url


def _iso_timestamp(value=None) -> str:
    if value is None:
        value = dj_timezone.now()
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _update_job(job: ETLJob, **fields):
    for key, value in fields.items():
        setattr(job, key, value)
    job.save(update_fields=[*fields.keys(), "updated_at"])


def _update_job_state(redis_client, job: ETLJob, errors: list | None = None):
    payload = {
        "job_id": job.job_id,
        "tenant_id": job.tenant_id,
        "loan_type": job.loan_type,
        "status": job.status,
        "progress_percentage": job.progress_percentage,
        "processed_rows": job.processed_rows,
        "started_at": _iso_timestamp(job.started_at) if job.started_at else None,
        "updated_at": _iso_timestamp(),
        "errors": errors if errors is not None else (job.errors or []),
    }
    redis_client.set(f"job:state:{job.job_id}", json.dumps(payload), ex=86400)


def _serialize_error_logs(error_logs) -> list[dict]:
    serialized = []
    for err in error_logs:
        message = err.message
        serialized.append(
            {
                "row_number": err.row_number,
                "field": err.field,
                "error_type": err.error_type,
                "message": message,
                "error_message": message,
            }
        )
    return serialized


def _make_progress_callback(job: ETLJob, redis_client):
    def on_progress(processed_rows: int, progress_percentage: int, errors):
        serialized_errors = [
            {
                "row_number": item[0],
                "field": item[1],
                "error_type": item[2],
                "message": item[3],
                "error_message": item[3],
            }
            for item in errors
        ]
        _update_job(
            job,
            processed_rows=processed_rows,
            progress_percentage=progress_percentage,
            errors=serialized_errors,
        )
        _update_job_state(redis_client, job, serialized_errors)

    return on_progress


@shared_task(bind=True)
def run_etl_pipeline(self, job_id: str, tenant_id: str, loan_type: str):
    redis_client = get_redis_client()
    job = ETLJob.objects.get(job_id=job_id)

    if job.status == ETLJob.STATUS_CANCELLED or is_cancel_requested(job_id):
        release_sync_lock(redis_client, tenant_id, loan_type, job_id)
        clear_cancel_flags(job_id)
        return {"cancelled": True}

    try:
        import adapter_core

        started_at = dj_timezone.now()
        _update_job(
            job,
            status=ETLJob.STATUS_PROCESSING,
            started_at=started_at,
            progress_percentage=5,
        )
        _update_job_state(redis_client, job)

        if is_cancel_requested(job_id):
            return {"cancelled": True}

        credits_url, payments_url = _bank_urls(tenant_id, loan_type)
        result = adapter_core.execute_etl_pipeline(
            job_id,
            tenant_id,
            loan_type,
            credits_url,
            payments_url,
            _database_url(),
            _make_progress_callback(job, redis_client),
        )

        job.refresh_from_db()
        if job.status == ETLJob.STATUS_CANCELLED or is_cancel_requested(job_id):
            return {"cancelled": True}

        errors = _serialize_error_logs(result.error_logs)
        error_count = len(errors)
        validation_summary = {
            "is_valid": result.success and error_count == 0,
            "error_count": error_count,
            "critical_failures": errors[:10],
        }

        final_status = ETLJob.STATUS_COMPLETED if result.success else ETLJob.STATUS_FAILED
        _update_job(
            job,
            status=final_status,
            completed_at=dj_timezone.now(),
            progress_percentage=100,
            processed_rows=result.processed_rows_count,
            errors=errors,
            validation_summary=validation_summary,
            result=(
                f"Ingested {result.metrics.total_credits_ingested} credits and "
                f"{result.metrics.total_payments_ingested} payments in "
                f"{result.execution_duration_seconds:.2f}s"
            ),
        )
        _update_job_state(redis_client, job, errors)

        if not result.success:
            raise RuntimeError(errors[0]["message"] if errors else "ETL pipeline failed")

        return {
            "credits_ingested": result.metrics.total_credits_ingested,
            "payments_ingested": result.metrics.total_payments_ingested,
            "errors": errors,
        }
    except Exception as exc:
        job.refresh_from_db()
        if job.status == ETLJob.STATUS_CANCELLED or is_cancel_requested(job_id):
            return {"cancelled": True}
        error = {"row_number": 0, "field": "pipeline", "error_type": "PIPELINE_ERROR", "message": str(exc), "error_message": str(exc)}
        _update_job(
            job,
            status=ETLJob.STATUS_FAILED,
            completed_at=dj_timezone.now(),
            result=str(exc),
            errors=[error],
            validation_summary={"is_valid": False, "error_count": 1, "critical_failures": [str(exc)]},
        )
        _update_job_state(redis_client, job, [error])
        raise
    finally:
        release_sync_lock(redis_client, tenant_id, loan_type, job_id)
        clear_cancel_flags(job_id)
