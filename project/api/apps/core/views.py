import datetime
import jwt
from django.conf import settings
from django.http import JsonResponse
from rest_framework.decorators import api_view
from rest_framework.request import Request


@api_view(["GET"])
def health(request: Request):
    return JsonResponse({"status": "ok", "service": "core_backend_api"})


@api_view(["POST"])
def issue_token(request: Request):
    tenant_id = request.data.get("tenant_id", "tenant_alpha")
    payload = {
        "tenant_id": tenant_id,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=8),
        "iat": datetime.datetime.utcnow(),
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")
    return JsonResponse({"access_token": token, "tenant_id": tenant_id})
