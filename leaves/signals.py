from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from accounts.models import EmployeeProfile

from .services import ensure_default_leave_allocations_for_employee


@receiver(post_save, sender=EmployeeProfile)
def assign_default_leave_allocations(sender, instance, **kwargs) -> None:
    ensure_default_leave_allocations_for_employee(instance)


# ── WFH Balance signals ───────────────────────────────────────────────────────

@receiver(pre_save, sender="leaves.LeaveRequest")
def capture_leave_old_status(sender, instance, **kwargs) -> None:
    """Store the previous status so post_save can detect transitions."""
    if instance.pk:
        try:
            instance._old_status = sender.objects.get(pk=instance.pk).status
        except sender.DoesNotExist:
            instance._old_status = None
    else:
        instance._old_status = None


@receiver(post_save, sender="leaves.LeaveRequest")
def sync_wfh_balance_on_status_change(sender, instance, created, **kwargs) -> None:
    """
    Deduct WFH balance when a request is approved.
    Restore it when an approved request is rejected or cancelled.
    """
    if not instance.leave_type.is_wfh:
        return

    from .models import WFHBalance

    old_status = getattr(instance, "_old_status", None)
    new_status = instance.status

    APPROVED = instance.StatusChoices.APPROVED
    TERMINAL = {instance.StatusChoices.REJECTED, instance.StatusChoices.CANCELLED}

    try:
        wfh_bal, _ = WFHBalance.objects.get_or_create(employee=instance.employee)
    except Exception:
        return

    # Newly approved → deduct balance
    if new_status == APPROVED and old_status != APPROVED:
        wfh_bal.deduct(instance.number_of_days)

    # Was approved → now rejected or cancelled → restore balance
    elif old_status == APPROVED and new_status in TERMINAL:
        wfh_bal.restore(instance.number_of_days)
