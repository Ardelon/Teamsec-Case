from celery.result import AsyncResult
from django.utils import timezone as dj_timezone

from apps.core.services.redis_lock import get_redis_client, release_sync_lock
from apps.etl.models import ETLJob

CELERY_TASK_KEY = "job:celery:{job_id}"
CANCEL_FLAG_KEY = "job:cancel:{job_id}"
CANCEL_MESSAGE = "Sync cancelled by user"


def celery_task_key(job_id: str) -> str:
    return CELERY_TASK_KEY.format(job_id=job_id)


def cancel_flag_key(job_id: str) -> str:
    return CANCEL_FLAG_KEY.format(job_id=job_id)


def store_celery_task_id(job_id: str, task_id: str) -> None:
    get_redis_client().set(celery_task_key(job_id), task_id, ex=86400)


def get_celery_task_id(job_id: str) -> str | None:
    return get_redis_client().get(celery_task_key(job_id))


def mark_cancel_requested(job_id: str) -> None:
    get_redis_client().set(cancel_flag_key(job_id), "1", ex=86400)


def is_cancel_requested(job_id: str) -> bool:
    return bool(get_redis_client().get(cancel_flag_key(job_id)))


def clear_cancel_flags(job_id: str) -> None:
    client = get_redis_client()
    client.delete(cancel_flag_key(job_id), celery_task_key(job_id))


def _update_job_state(redis_client, job: ETLJob, errors: list | None = None) -> None:
    import json
    from datetime import timezone

    def iso(value=None):
        if value is None:
            value = dj_timezone.now()
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    payload = {
        "job_id": job.job_id,
        "tenant_id": job.tenant_id,
        "loan_type": job.loan_type,
        "status": job.status,
        "progress_percentage": job.progress_percentage,
        "processed_rows": job.processed_rows,
        "started_at": iso(job.started_at) if job.started_at else None,
        "updated_at": iso(),
        "errors": errors if errors is not None else (job.errors or []),
    }
    redis_client.set(f"job:state:{job.job_id}", json.dumps(payload), ex=86400)


def cancel_sync_job(job: ETLJob) -> ETLJob:
    if job.status not in {ETLJob.STATUS_QUEUED, ETLJob.STATUS_PROCESSING}:
        raise ValueError("Only queued or processing jobs can be cancelled")

    redis_client = get_redis_client()
    mark_cancel_requested(job.job_id)

    task_id = get_celery_task_id(job.job_id)
    if task_id:
        AsyncResult(task_id).revoke(terminate=True, signal="SIGTERM")

    error = {
        "row_number": 0,
        "field": "pipeline",
        "error_type": "CANCELLED",
        "message": CANCEL_MESSAGE,
        "error_message": CANCEL_MESSAGE,
    }
    job.status = ETLJob.STATUS_CANCELLED
    job.completed_at = dj_timezone.now()
    job.result = CANCEL_MESSAGE
    job.errors = [error]
    job.validation_summary = {
        "is_valid": False,
        "error_count": 1,
        "critical_failures": [CANCEL_MESSAGE],
    }
    job.save(
        update_fields=[
            "status",
            "completed_at",
            "result",
            "errors",
            "validation_summary",
            "updated_at",
        ]
    )
    _update_job_state(redis_client, job, [error])
    release_sync_lock(redis_client, job.tenant_id, job.loan_type, job.job_id)
    redis_client.delete(celery_task_key(job.job_id))
    return job
