import uuid

from django.http import JsonResponse
from django.shortcuts import render
from rest_framework.decorators import api_view
from rest_framework.request import Request

from apps.etl.models import ETLJob
from apps.etl.tasks import run_etl_pipeline


def dashboard(request):
    return render(request, "etl_dashboard.html")


@api_view(["GET"])
def list_jobs(request: Request):
    jobs = ETLJob.objects.all()[:50]
    data = [
        {
            "job_id": j.job_id,
            "tenant_id": j.tenant_id,
            "loan_type": j.loan_type,
            "status": j.status,
            "result": j.result,
            "created_at": j.created_at.isoformat(),
        }
        for j in jobs
    ]
    return JsonResponse({"jobs": data})


@api_view(["POST"])
def trigger_job(request: Request):
    tenant_id = request.data.get("tenant_id", "tenant_alpha")
    loan_type = request.data.get("loan_type", "mortgage")
    async_result = run_etl_pipeline.delay(tenant_id, loan_type)
    return JsonResponse({"job_id": async_result.id, "status": "queued"})


@api_view(["GET"])
def job_detail(request: Request, job_id: str):
    try:
        job = ETLJob.objects.get(job_id=job_id)
    except ETLJob.DoesNotExist:
        return JsonResponse({"error": "not found"}, status=404)
    return JsonResponse(
        {
            "job_id": job.job_id,
            "tenant_id": job.tenant_id,
            "loan_type": job.loan_type,
            "status": job.status,
            "result": job.result,
        }
    )
