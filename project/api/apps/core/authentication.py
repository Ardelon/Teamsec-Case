import jwt
from django.conf import settings
from rest_framework import authentication, exceptions


class JWTUser:
    is_authenticated = True

    def __init__(self, username: str, tenant_id: str):
        self.username = username
        self.tenant_id = tenant_id

    @property
    def is_anonymous(self):
        return False


class JWTAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith("Bearer "):
            return None

        token = auth_header[7:]
        try:
            payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=["HS256"])
        except jwt.PyJWTError as exc:
            raise exceptions.AuthenticationFailed("Invalid or expired token") from exc

        username = payload.get("sub")
        tenant_id = payload.get("tenant_id")
        if not username or not tenant_id:
            raise exceptions.AuthenticationFailed("Token missing required claims")

        return JWTUser(username=username, tenant_id=tenant_id), token
