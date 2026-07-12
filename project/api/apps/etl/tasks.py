import uuid

from celery import shared_task

from apps.etl.models import ETLJob


@shared_task(bind=True)
def run_etl_pipeline(self, tenant_id: str, loan_type: str):
    import adapter_core

    job_id = self.request.id or str(uuid.uuid4())
    job, _ = ETLJob.objects.update_or_create(
        job_id=job_id,
        defaults={
            "tenant_id": tenant_id,
            "loan_type": loan_type,
            "status": ETLJob.STATUS_RUNNING,
        },
    )
    try:
        result = adapter_core.execute_etl_pipeline(job_id, tenant_id, loan_type)
        job.status = ETLJob.STATUS_COMPLETED
        job.result = result
        job.save(update_fields=["status", "result", "updated_at"])
        return result
    except Exception as exc:
        job.status = ETLJob.STATUS_FAILED
        job.result = str(exc)
        job.save(update_fields=["status", "result", "updated_at"])
        raise
