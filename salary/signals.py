from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender="salary.SalarySetup")
def sync_payslips_on_setup_change(sender, instance, **kwargs):
    """When a SalarySetup is saved, recalculate payslips for all non-locked runs."""
    from .models import PayrollRun
    from .services import create_or_update_payslip_for_run

    if not instance.is_active:
        return

    open_runs = PayrollRun.objects.exclude(status=PayrollRun.StatusChoices.LOCKED)
    for run in open_runs:
        try:
            create_or_update_payslip_for_run(run, instance.employee)
        except Exception:
            pass
