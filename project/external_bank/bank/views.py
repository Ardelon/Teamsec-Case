from django.http import FileResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from bank.constants import CREDITS_FILENAME, LOAN_TYPES, PAYMENTS_FILENAME, TENANT_IDS
from bank.models import PortfolioUpload
from bank.serializers import UploadSerializer, build_upload_response
from bank.services.storage import (
    credits_path,
    list_portfolios,
    payments_path,
    save_upload_files,
    validate_loan_type,
    validate_tenant_id,
)
from bank.services.streaming import parse_multiply, stream_json_file


def health(request):
    return JsonResponse({"status": "ok", "service": "external_bank_sim"})


def portal(request):
    return render(
        request,
        "portal.html",
        {
            "tenants": TENANT_IDS,
            "loan_types": LOAN_TYPES,
            "portfolios": list_portfolios(),
        },
    )


def portfolio_list_partial(request):
    return render(request, "partials/portfolio_list.html", {"portfolios": list_portfolios()})


class BankUploadView(APIView):
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        serializer = UploadSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        credits_size, payments_size = save_upload_files(
            data["tenant_id"],
            data["loan_type"],
            data["credit_file"],
            data["payment_plan_file"],
        )

        upload, _ = PortfolioUpload.objects.update_or_create(
            tenant_id=data["tenant_id"],
            loan_type=data["loan_type"],
            defaults={
                "credits_size_bytes": credits_size,
                "payments_size_bytes": payments_size,
            },
        )

        return Response(
            build_upload_response(
                data["tenant_id"],
                data["loan_type"],
                credits_size,
                payments_size,
                upload.uploaded_at.isoformat().replace("+00:00", "Z"),
            ),
            status=status.HTTP_201_CREATED,
        )


def _validate_tenant_loan(request):
    tenant_id = request.GET.get("tenant_id", "")
    loan_type = request.GET.get("loan_type", "")
    errors = {}
    tenant_error = validate_tenant_id(tenant_id)
    if tenant_error:
        errors["tenant_id"] = tenant_error
    loan_error = validate_loan_type(loan_type)
    if loan_error:
        errors["loan_type"] = loan_error
    return tenant_id, loan_type, errors


def _export_file(request, file_kind: str):
    tenant_id, loan_type, errors = _validate_tenant_loan(request)
    if errors:
        return JsonResponse(errors, status=400)

    if file_kind == "credits":
        file_path = credits_path(tenant_id, loan_type)
        filename = CREDITS_FILENAME
        export_name = "credits.json"
    else:
        file_path = payments_path(tenant_id, loan_type)
        filename = PAYMENTS_FILENAME
        export_name = "payments.json"

    if not file_path.exists():
        return JsonResponse(
            {"detail": f"No {filename} found for {tenant_id}/{loan_type}"},
            status=404,
        )

    multiply = parse_multiply(request.GET.get("multiply"))
    response = StreamingHttpResponse(
        stream_json_file(file_path, multiply),
        content_type="application/json",
    )
    response["Content-Disposition"] = f'inline; filename="{export_name}"'
    return response


def export_credits(request):
    return _export_file(request, "credits")


def export_payments(request):
    return _export_file(request, "payments")


def _download_file(request, file_kind: str):
    tenant_id, loan_type, errors = _validate_tenant_loan(request)
    if errors:
        return JsonResponse(errors, status=400)

    fmt = (request.GET.get("format") or "csv").lower()
    if fmt not in {"csv", "json"}:
        return JsonResponse({"format": "Must be csv or json"}, status=400)

    if file_kind == "credits":
        file_path = credits_path(tenant_id, loan_type)
        csv_name = CREDITS_FILENAME
        json_name = "credits.json"
    else:
        file_path = payments_path(tenant_id, loan_type)
        csv_name = PAYMENTS_FILENAME
        json_name = "payments.json"

    if not file_path.exists():
        return JsonResponse(
            {"detail": f"No {csv_name} found for {tenant_id}/{loan_type}"},
            status=404,
        )

    if fmt == "csv":
        return FileResponse(
            file_path.open("rb"),
            as_attachment=True,
            filename=f"{tenant_id}_{loan_type}_{csv_name}",
            content_type="text/csv",
        )

    multiply = parse_multiply(request.GET.get("multiply"))
    response = StreamingHttpResponse(
        stream_json_file(file_path, multiply),
        content_type="application/json",
    )
    response["Content-Disposition"] = (
        f'attachment; filename="{tenant_id}_{loan_type}_{json_name}"'
    )
    return response


def download_credits(request):
    return _download_file(request, "credits")


def download_payments(request):
    return _download_file(request, "payments")
