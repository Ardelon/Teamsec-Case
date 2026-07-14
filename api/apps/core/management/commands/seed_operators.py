from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from apps.core.models import OperatorProfile


class Command(BaseCommand):
    help = "Seed demo operator accounts for tenant-scoped login"

    def handle(self, *args, **options):
        operators = [
            ("operator_admin", "secure_cleartext_password", "BANK001"),
            ("operator_bank2", "secure_cleartext_password", "BANK002"),
            ("operator_bank3", "secure_cleartext_password", "BANK003"),
        ]

        for username, password, tenant_id in operators:
            user, created = User.objects.get_or_create(username=username)
            user.set_password(password)
            user.save()
            OperatorProfile.objects.get_or_create(user=user, tenant_id=tenant_id)
            action = "Created" if created else "Updated"
            self.stdout.write(self.style.SUCCESS(f"{action} {username} for {tenant_id}"))
