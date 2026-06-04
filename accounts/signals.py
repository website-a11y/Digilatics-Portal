from django.contrib.auth import get_user_model
from django.db.models.signals import post_migrate, post_save
from django.dispatch import receiver

from .services import (
    ensure_employee_profile_for_user,
    ensure_employee_profiles_for_existing_users,
    ensure_role_groups,
)


User = get_user_model()


@receiver(post_migrate)
def create_default_role_groups(**kwargs) -> None:
    if kwargs.get("app_config") and kwargs["app_config"].name != "accounts":
        return
    ensure_role_groups()
    ensure_employee_profiles_for_existing_users()


@receiver(post_save, sender=User)
def create_employee_profile_for_new_user(sender, instance, created, **kwargs) -> None:
    if created:
        ensure_employee_profile_for_user(instance)
