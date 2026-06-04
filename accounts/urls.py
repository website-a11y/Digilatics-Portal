from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("employees/", views.employee_directory, name="employee_directory"),
    path("employees/<int:pk>/", views.employee_profile, name="employee_profile"),
    # Password setup (sent via email when a new employee is created)
    path(
        "accounts/setup-password/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="accounts/password_setup_confirm.html",
            success_url="/accounts/setup-password/done/",
        ),
        name="password_setup_confirm",
    ),
    path(
        "accounts/setup-password/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="accounts/password_setup_complete.html",
        ),
        name="password_setup_complete",
    ),
]
