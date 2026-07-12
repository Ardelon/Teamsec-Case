from decimal import Decimal

from django.db import models


class ETLJob(models.Model):
    STATUS_QUEUED = "QUEUED"
    STATUS_PROCESSING = "PROCESSING"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_FAILED = "FAILED"

    STATUS_CHOICES = [
        (STATUS_QUEUED, "Queued"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
    ]

    job_id = models.CharField(max_length=64, unique=True)
    tenant_id = models.CharField(max_length=64, db_index=True)
    loan_type = models.CharField(max_length=32, db_index=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    progress_percentage = models.IntegerField(default=0)
    processed_rows = models.IntegerField(default=0)
    result = models.TextField(blank=True, default="")
    errors = models.JSONField(default=list, blank=True)
    validation_summary = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.job_id} ({self.tenant_id}/{self.loan_type})"


class CreditRecord(models.Model):
    tenant_id = models.CharField(max_length=64, db_index=True)
    loan_type = models.CharField(max_length=32, db_index=True)
    loan_account_number = models.CharField(max_length=64)
    customer_id = models.CharField(max_length=64, blank=True, default="")
    customer_type = models.CharField(max_length=16, blank=True, default="")
    loan_status_code = models.CharField(max_length=16, blank=True, default="")
    days_past_due = models.IntegerField(null=True, blank=True)
    final_maturity_date = models.DateField(null=True, blank=True)
    total_installment_count = models.IntegerField(null=True, blank=True)
    outstanding_installment_count = models.IntegerField(null=True, blank=True)
    paid_installment_count = models.IntegerField(null=True, blank=True)
    first_payment_date = models.DateField(null=True, blank=True)
    original_loan_amount = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    outstanding_principal_balance = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    nominal_interest_rate = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    total_interest_amount = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    kkdf_rate = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    kkdf_amount = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    bsmv_rate = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    bsmv_amount = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    grace_period_months = models.IntegerField(null=True, blank=True)
    installment_frequency = models.IntegerField(null=True, blank=True)
    loan_start_date = models.DateField(null=True, blank=True)
    loan_closing_date = models.DateField(null=True, blank=True)
    internal_rating = models.IntegerField(null=True, blank=True)
    external_rating = models.IntegerField(null=True, blank=True)
    retail_specific_attributes = models.JSONField(default=dict, blank=True)
    commercial_specific_attributes = models.JSONField(default=dict, blank=True)
    snapshot_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("tenant_id", "loan_type", "loan_account_number")]
        indexes = [
            models.Index(fields=["tenant_id", "loan_type"]),
        ]

    def __str__(self):
        return f"{self.loan_account_number} ({self.tenant_id}/{self.loan_type})"


class PaymentInstallment(models.Model):
    credit = models.ForeignKey(CreditRecord, on_delete=models.CASCADE, related_name="payment_schedule")
    installment_number = models.IntegerField()
    actual_payment_date = models.DateField(null=True, blank=True)
    scheduled_payment_date = models.DateField(null=True, blank=True)
    installment_amount = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    principal_component = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    interest_component = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    kkdf_component = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    bsmv_component = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    installment_status = models.CharField(max_length=16, blank=True, default="")
    remaining_principal = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    remaining_interest = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    remaining_kkdf = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    remaining_bsmv = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)

    class Meta:
        unique_together = [("credit", "installment_number")]
        ordering = ["installment_number"]

    @staticmethod
    def decimal_or_none(value):
        if value in (None, ""):
            return None
        return Decimal(str(value))
