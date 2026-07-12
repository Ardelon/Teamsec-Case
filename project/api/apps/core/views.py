import datetime

import jwt
from django.conf import settings
from django.contrib.auth import authenticate
from django.http import JsonResponse
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.models import OperatorProfile


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request: Request):
    return JsonResponse({"status": "ok", "service": "core_backend_api"})


@api_view(["POST"])
@permission_classes([AllowAny])
def login(request: Request):
    username = request.data.get("username", "")
    password = request.data.get("password", "")
    tenant_id = request.data.get("tenant_id", "")

    if not username or not password or not tenant_id:
        return Response(
            {"error": "username, password, and tenant_id are required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    user = authenticate(username=username, password=password)
    if user is None:
        return Response({"error": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED)

    if not OperatorProfile.objects.filter(user=user, tenant_id=tenant_id).exists():
        return Response(
            {"error": "Operator is not authorized for this tenant"},
            status=status.HTTP_403_FORBIDDEN,
        )

    expires_at = datetime.datetime.utcnow() + datetime.timedelta(hours=settings.JWT_EXPIRY_HOURS)
    payload = {
        "sub": username,
        "tenant_id": tenant_id,
        "exp": expires_at,
        "iat": datetime.datetime.utcnow(),
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")

    return Response(
        {
            "token": token,
            "expires_at": expires_at.replace(tzinfo=datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
            "tenant_id": tenant_id,
        }
    )
