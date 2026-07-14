from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="PortfolioUpload",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "tenant_id",
                    models.CharField(
                        choices=[("BANK001", "BANK001"), ("BANK002", "BANK002"), ("BANK003", "BANK003")],
                        max_length=16,
                    ),
                ),
                (
                    "loan_type",
                    models.CharField(
                        choices=[("RETAIL", "RETAIL"), ("COMMERCIAL", "COMMERCIAL")],
                        max_length=16,
                    ),
                ),
                ("credits_size_bytes", models.BigIntegerField()),
                ("payments_size_bytes", models.BigIntegerField()),
                ("uploaded_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("tenant_id", "loan_type"),
                        name="unique_portfolio_upload",
                    )
                ],
            },
        ),
    ]
