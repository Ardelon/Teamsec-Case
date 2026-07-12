from django.shortcuts import render
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.permissions import TenantScopedPermission
from apps.core.services.redis_lock import acquire_sync_lock, get_active_job_id, get_redis_client
from apps.etl.models import ETLJob
from apps.etl.serializers import JobStatusSerializer, SyncRequestSerializer, SyncResponseSerializer, new_job_id
from apps.etl.services.profiling import build_profiling_payload
from apps.etl.services.warehouse import get_data_snapshot
from apps.etl.tasks import run_etl_pipeline


def _tenant_from_request(request: Request) -> str:
    return request.user.tenant_id


def _loan_type_from_request(request: Request) -> str | None:
    return request.query_params.get("loan_type") or request.data.get("loan_type")


def _forbidden_if_tenant_mismatch(request: Request) -> Response | None:
    token_tenant = _tenant_from_request(request)
    for source in (request.query_params.get("tenant_id"), request.data.get("tenant_id")):
        if source and source != token_tenant:
            return Response({"error": "Tenant mismatch with token claims"}, status=status.HTTP_403_FORBIDDEN)
    return None


@api_view(["POST"])
@permission_classes([IsAuthenticated, TenantScopedPermission])
def sync_data(request: Request):
    mismatch = _forbidden_if_tenant_mismatch(request)
    if mismatch:
        return mismatch

    serializer = SyncRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    tenant_id = _tenant_from_request(request)
    loan_type = serializer.validated_data["loan_type"].upper()
    job_id = new_job_id()
    redis_client = get_redis_client()

    if not acquire_sync_lock(redis_client, tenant_id, loan_type, job_id):
        active_job_id = get_active_job_id(redis_client, tenant_id, loan_type)
        return Response(
            {
                "error": "A pipeline processing cycle is actively running for this specific tenant and credit selection selection.",
                "active_job_id": active_job_id,
            },
            status=status.HTTP_409_CONFLICT,
        )

    job = ETLJob.objects.create(
        job_id=job_id,
        tenant_id=tenant_id,
        loan_type=loan_type,
        status=ETLJob.STATUS_QUEUED,
    )
    run_etl_pipeline.delay(job_id, tenant_id, loan_type)

    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/sync_status.html", {"job": job})

    response = SyncResponseSerializer(job).data
    return Response(response, status=status.HTTP_202_ACCEPTED)


@api_view(["GET"])
@permission_classes([IsAuthenticated, TenantScopedPermission])
def sync_status(request: Request, job_id: str):
    mismatch = _forbidden_if_tenant_mismatch(request)
    if mismatch:
        return mismatch

    try:
        job = ETLJob.objects.get(job_id=job_id)
    except ETLJob.DoesNotExist:
        return Response({"error": "Job not found"}, status=status.HTTP_404_NOT_FOUND)

    if job.tenant_id != _tenant_from_request(request):
        return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/sync_status.html", {"job": job})

    return Response(JobStatusSerializer(job).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated, TenantScopedPermission])
def data_snapshot(request: Request):
    mismatch = _forbidden_if_tenant_mismatch(request)
    if mismatch:
        return mismatch

    loan_type = _loan_type_from_request(request)
    if not loan_type:
        return Response({"error": "loan_type query parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

    tenant_id = _tenant_from_request(request)
    payload = get_data_snapshot(tenant_id, loan_type.upper())
    return Response(payload)


@api_view(["GET"])
@permission_classes([IsAuthenticated, TenantScopedPermission])
def profiling_metrics(request: Request):
    mismatch = _forbidden_if_tenant_mismatch(request)
    if mismatch:
        return mismatch

    loan_type = _loan_type_from_request(request)
    if not loan_type:
        return Response({"error": "loan_type query parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

    tenant_id = _tenant_from_request(request)
    payload = build_profiling_payload(tenant_id, loan_type.upper())
    return Response(payload)


def dashboard(request):
    return render(request, "dashboard.html")


def login_page(request):
    return render(request, "login.html")
