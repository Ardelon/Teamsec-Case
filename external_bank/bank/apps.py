from django.apps import AppConfig


class BankConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "bank"

    def ready(self):
        from django.conf import settings

        settings.STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
