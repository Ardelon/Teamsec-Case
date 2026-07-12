from django.http import JsonResponse, StreamingHttpResponse
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from bank.constants import CREDITS_FILENAME, PAYMENTS_FILENAME
from bank.models import PortfolioUpload
from bank.serializers import UploadSerializer, build_upload_response
from bank.services.storage import (
    credits_path,
    payments_path,
    save_upload_files,
    validate_loan_type,
    validate_tenant_id,
)
from bank.services.streaming import parse_multiply, stream_csv_file


def health(request):
    return JsonResponse({"status": "ok", "service": "external_bank_sim"})


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


def _export_file(request, file_kind: str):
    tenant_id = request.GET.get("tenant_id", "")
    loan_type = request.GET.get("loan_type", "")

    errors = {}
    tenant_error = validate_tenant_id(tenant_id)
    if tenant_error:
        errors["tenant_id"] = tenant_error
    loan_error = validate_loan_type(loan_type)
    if loan_error:
        errors["loan_type"] = loan_error
    if errors:
        return JsonResponse(errors, status=400)

    if file_kind == "credits":
        file_path = credits_path(tenant_id, loan_type)
        filename = CREDITS_FILENAME
    else:
        file_path = payments_path(tenant_id, loan_type)
        filename = PAYMENTS_FILENAME

    if not file_path.exists():
        return JsonResponse(
            {"detail": f"No {filename} found for {tenant_id}/{loan_type}"},
            status=404,
        )

    multiply = parse_multiply(request.GET.get("multiply"))
    response = StreamingHttpResponse(
        stream_csv_file(file_path, multiply),
        content_type="text/csv",
    )
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


def export_credits(request):
    return _export_file(request, "credits")


def export_payments(request):
    return _export_file(request, "payments")
