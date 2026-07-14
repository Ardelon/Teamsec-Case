from django.db import models

from bank.constants import LOAN_TYPE_CHOICES, TENANT_CHOICES


class PortfolioUpload(models.Model):
    tenant_id = models.CharField(max_length=16, choices=TENANT_CHOICES)
    loan_type = models.CharField(max_length=16, choices=LOAN_TYPE_CHOICES)
    credits_size_bytes = models.BigIntegerField()
    payments_size_bytes = models.BigIntegerField()
    uploaded_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "loan_type"],
                name="unique_portfolio_upload",
            )
        ]

    def __str__(self):
        return f"{self.tenant_id}/{self.loan_type}"
