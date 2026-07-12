from rest_framework import permissions


class TenantScopedPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user or not getattr(user, "is_authenticated", False):
            return False

        token_tenant = getattr(user, "tenant_id", None)
        if not token_tenant:
            return False

        body_tenant = None
        if hasattr(request, "data") and request.data:
            body_tenant = request.data.get("tenant_id")

        query_tenant = request.query_params.get("tenant_id")
        for param_tenant in (body_tenant, query_tenant):
            if param_tenant and param_tenant != token_tenant:
                return False

        return True
