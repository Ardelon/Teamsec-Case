import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="CreditRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tenant_id", models.CharField(db_index=True, max_length=64)),
                ("loan_type", models.CharField(db_index=True, max_length=32)),
                ("loan_account_number", models.CharField(max_length=64)),
                ("customer_id", models.CharField(blank=True, default="", max_length=64)),
                ("customer_type", models.CharField(blank=True, default="", max_length=16)),
                ("loan_status_code", models.CharField(blank=True, default="", max_length=16)),
                ("days_past_due", models.IntegerField(blank=True, null=True)),
                ("final_maturity_date", models.DateField(blank=True, null=True)),
                ("total_installment_count", models.IntegerField(blank=True, null=True)),
                ("outstanding_installment_count", models.IntegerField(blank=True, null=True)),
                ("paid_installment_count", models.IntegerField(blank=True, null=True)),
                ("first_payment_date", models.DateField(blank=True, null=True)),
                ("original_loan_amount", models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ("outstanding_principal_balance", models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ("nominal_interest_rate", models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ("total_interest_amount", models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ("kkdf_rate", models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ("kkdf_amount", models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ("bsmv_rate", models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ("bsmv_amount", models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ("grace_period_months", models.IntegerField(blank=True, null=True)),
                ("installment_frequency", models.IntegerField(blank=True, null=True)),
                ("loan_start_date", models.DateField(blank=True, null=True)),
                ("loan_closing_date", models.DateField(blank=True, null=True)),
                ("internal_rating", models.IntegerField(blank=True, null=True)),
                ("external_rating", models.IntegerField(blank=True, null=True)),
                ("retail_specific_attributes", models.JSONField(blank=True, default=dict)),
                ("commercial_specific_attributes", models.JSONField(blank=True, default=dict)),
                ("snapshot_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="ETLJob",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("job_id", models.CharField(max_length=64, unique=True)),
                ("tenant_id", models.CharField(db_index=True, max_length=64)),
                ("loan_type", models.CharField(db_index=True, max_length=32)),
                ("status", models.CharField(
                    choices=[
                        ("QUEUED", "Queued"),
                        ("PROCESSING", "Processing"),
                        ("COMPLETED", "Completed"),
                        ("FAILED", "Failed"),
                    ],
                    default="QUEUED",
                    max_length=16,
                )),
                ("progress_percentage", models.IntegerField(default=0)),
                ("processed_rows", models.IntegerField(default=0)),
                ("result", models.TextField(blank=True, default="")),
                ("errors", models.JSONField(blank=True, default=list)),
                ("validation_summary", models.JSONField(blank=True, default=dict)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="PaymentInstallment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("installment_number", models.IntegerField()),
                ("actual_payment_date", models.DateField(blank=True, null=True)),
                ("scheduled_payment_date", models.DateField(blank=True, null=True)),
                ("installment_amount", models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ("principal_component", models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ("interest_component", models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ("kkdf_component", models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ("bsmv_component", models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ("installment_status", models.CharField(blank=True, default="", max_length=16)),
                ("remaining_principal", models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ("remaining_interest", models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ("remaining_kkdf", models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ("remaining_bsmv", models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                (
                    "credit",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="payment_schedule",
                        to="etl.creditrecord",
                    ),
                ),
            ],
            options={
                "ordering": ["installment_number"],
                "unique_together": {("credit", "installment_number")},
            },
        ),
        migrations.AddIndex(
            model_name="creditrecord",
            index=models.Index(fields=["tenant_id", "loan_type"], name="etl_credit__tenant__8a0f0d_idx"),
        ),
        migrations.AlterUniqueTogether(
            name="creditrecord",
            unique_together={("tenant_id", "loan_type", "loan_account_number")},
        ),
    ]
