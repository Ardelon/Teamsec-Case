from rest_framework import authentication, exceptions
from rest_framework.authentication import SessionAuthentication as DRFSessionAuthentication


class JWTUser:
    is_authenticated = True

    def __init__(self, username: str, tenant_id: str):
        self.username = username
        self.tenant_id = tenant_id

    @property
    def is_anonymous(self):
        return False


class SessionOperatorAuthentication(DRFSessionAuthentication):
    """Authenticate from the Django session cookie (HttpOnly)."""

    def authenticate(self, request):
        operator = request.session.get("operator")
        if not operator:
            return None

        username = operator.get("username")
        tenant_id = operator.get("tenant_id")
        if not username or not tenant_id:
            raise exceptions.AuthenticationFailed("Invalid session")

        self.enforce_csrf(request)
        return JWTUser(username=username, tenant_id=tenant_id), None


class BearerJWTAuthentication(authentication.BaseAuthentication):
    """Optional Bearer JWT for API clients (Postman, scripts)."""

    def authenticate(self, request):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith("Bearer "):
            return None

        import jwt
        from django.conf import settings

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


# Backward-compatible alias used in older imports/docs
JWTAuthentication = BearerJWTAuthentication
