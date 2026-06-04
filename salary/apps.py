from django.apps import AppConfig


class SalaryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "salary"
    verbose_name = "Salary Management"

    def ready(self):
        import salary.signals  # noqa: F401
