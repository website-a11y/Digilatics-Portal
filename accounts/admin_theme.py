from django.db import OperationalError, ProgrammingError
from django.templatetags.static import static
from django.urls import NoReverseMatch, reverse

from .models import EmployeeProfile


def brand_logo(_request) -> str:
    return ""


def brand_icon(_request) -> str:
    return static("accounts/branding/digilatics-symbol.svg")


def login_image(_request) -> str:
    return static("accounts/branding/digilatics-login-art.svg")


def _safe_reverse(name: str) -> str:
    try:
        return reverse(name)
    except NoReverseMatch:
        return "#"


def sidebar_navigation(_request):
    return [
        {
            "title": "HRIS Workspace",
            "items": [
                {
                    "title": "Dashboard",
                    "icon": "dashboard",
                    "link": _safe_reverse("admin:index"),
                },
                {
                    "title": "Employees",
                    "icon": "badge",
                    "link": _safe_reverse("admin:accounts_employeeprofile_changelist"),
                },
                {
                    "title": "Create Employee",
                    "icon": "person_add",
                    "link": _safe_reverse("admin:accounts_employeeprofile_add"),
                },
            ],
        },
        {
            "title": "Access Control",
            "items": [
                {
                    "title": "Users",
                    "icon": "shield_person",
                    "link": _safe_reverse("admin:auth_user_changelist"),
                },
                {
                    "title": "Groups",
                    "icon": "groups",
                    "link": _safe_reverse("admin:auth_group_changelist"),
                },
            ],
        },
    ]
