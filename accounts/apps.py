from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
    verbose_name = "HR Accounts"

    def ready(self) -> None:
        import accounts.signals  # noqa: F401
        from digilatics_hris.admin_site import patch_admin_index
        patch_admin_index()
