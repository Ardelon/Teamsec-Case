from django.contrib.auth.models import User
from django.db import models


class OperatorProfile(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="operator_profiles")
    tenant_id = models.CharField(max_length=64)

    class Meta:
        unique_together = [("user", "tenant_id")]

    def __str__(self):
        return f"{self.user.username}@{self.tenant_id}"
