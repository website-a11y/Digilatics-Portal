from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "portal"

urlpatterns = [
    path("login/",                          views.portal_login,                name="login"),
    path("logout/",                         views.portal_logout,               name="logout"),

    # ── Password reset ────────────────────────────────────────────────────────
    path("password-reset/", auth_views.PasswordResetView.as_view(
        template_name="portal/password_reset.html",
        email_template_name="portal/password_reset_email.txt",
        html_email_template_name="portal/password_reset_email.html",
        subject_template_name="portal/password_reset_subject.txt",
        success_url="/portal/password-reset/done/",
    ), name="password_reset"),
    path("password-reset/done/", auth_views.PasswordResetDoneView.as_view(
        template_name="portal/password_reset_done.html",
    ), name="password_reset_done"),
    path("reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(
        template_name="portal/password_reset_confirm.html",
        success_url="/portal/password-reset/complete/",
    ), name="password_reset_confirm"),
    path("password-reset/complete/", auth_views.PasswordResetCompleteView.as_view(
        template_name="portal/password_reset_complete.html",
    ), name="password_reset_complete"),
    path("",                                views.portal_dashboard,            name="dashboard"),
    path("attendance/",                     views.portal_attendance,           name="attendance"),
    path("leave/",                          views.portal_leave,                name="leave"),
    path("short-leave/apply/",              views.portal_short_leave_apply,    name="short_leave_apply"),
    path("short-leave/<int:pk>/cancel/",    views.portal_short_leave_cancel,   name="short_leave_cancel"),
    path("manager/short-leave/<int:pk>/action/", views.portal_manager_short_leave_action, name="manager_short_leave_action"),
    path("profile/",                        views.portal_profile,              name="profile"),
    path("payslips/",                       views.portal_payslips,             name="payslips"),
    path("payslips/<int:pk>/",              views.portal_payslip_detail,       name="payslip_detail"),
    path("punch/",                          views.portal_punch,                name="punch"),
    path("manager/",                        views.portal_manager_dashboard,    name="manager_dashboard"),
    path("manager/attendance/",             views.portal_manager_attendance,   name="manager_attendance"),
    path("manager/attendance/export/",      views.portal_manager_attendance_export, name="manager_attendance_export"),
    path("manager/leave/<int:pk>/action/",  views.portal_manager_leave_action, name="manager_leave_action"),

    # ── HR Admin Panel ────────────────────────────────────────────────────────
    path("hr/",                                         views.hr_dashboard,               name="hr_dashboard"),

    # Employees
    path("hr/employees/",                               views.hr_employees,               name="hr_employees"),
    path("hr/employees/bulk-delete/",                   views.hr_employees_bulk_delete,   name="hr_employees_bulk_delete"),
    path("hr/employees/add/",                           views.hr_employee_edit,           name="hr_employee_add"),
    path("hr/employees/<int:pk>/",                      views.hr_employee_detail,         name="hr_employee_detail"),
    path("hr/employees/<int:pk>/edit/",                 views.hr_employee_edit,           name="hr_employee_edit"),

    # Attendance
    path("hr/attendance/",                              views.hr_attendance,              name="hr_attendance"),
    path("hr/attendance/export/",                       views.hr_attendance_export,        name="hr_attendance_export"),
    path("hr/attendance/record/add/",                   views.hr_attendance_record_edit,  name="hr_attendance_record_add"),
    path("hr/attendance/record/<int:pk>/",              views.hr_attendance_record_edit,  name="hr_attendance_record_edit"),
    path("hr/attendance/record/<int:pk>/delete/",       views.hr_attendance_record_delete, name="hr_attendance_record_delete"),
    path("hr/attendance/holidays/",                     views.hr_holidays,                name="hr_holidays"),
    path("hr/attendance/holidays/add/",                 views.hr_holiday_edit,            name="hr_holiday_add"),
    path("hr/attendance/holidays/<int:pk>/",            views.hr_holiday_edit,            name="hr_holiday_edit"),
    path("hr/attendance/holidays/<int:pk>/delete/",     views.hr_holiday_delete,          name="hr_holiday_delete"),
    path("hr/attendance/shifts/",                       views.hr_shifts,                  name="hr_shifts"),
    path("hr/attendance/shifts/add/",                   views.hr_shift_edit,              name="hr_shift_add"),
    path("hr/attendance/shifts/<int:pk>/",              views.hr_shift_edit,              name="hr_shift_edit"),
    path("hr/attendance/shifts/<int:pk>/delete/",       views.hr_shift_delete,            name="hr_shift_delete"),
    path("hr/settings/",                                views.hr_settings,                name="hr_settings"),

    # Leaves
    path("hr/leaves/",                                  views.hr_leaves,                  name="hr_leaves"),
    path("hr/leaves/<int:pk>/action/",                  views.hr_leave_action,            name="hr_leave_action"),
    # Short Leave
    path("hr/short-leaves/",                            views.hr_short_leaves,            name="hr_short_leaves"),
    path("hr/short-leaves/<int:pk>/action/",            views.hr_short_leave_action,      name="hr_short_leave_action"),
    path("hr/short-leaves/policy/",                     views.hr_short_leave_policy,      name="hr_short_leave_policy"),

    # Payroll
    path("hr/payroll/",                                 views.hr_payroll,                 name="hr_payroll"),
    path("hr/payroll/create/",                          views.hr_payroll_create,          name="hr_payroll_create"),
    path("hr/payroll/<int:pk>/",                        views.hr_payroll_detail,          name="hr_payroll_detail"),
    path("hr/payroll/<int:pk>/generate/",               views.hr_payroll_generate,        name="hr_payroll_generate"),
    path("hr/payroll/<int:pk>/finalize/",               views.hr_payroll_finalize,        name="hr_payroll_finalize"),
    path("hr/payroll/<int:pk>/lock/",                   views.hr_payroll_lock,            name="hr_payroll_lock"),
    path("hr/payroll/payslip/<int:pk>/",                views.hr_payslip_edit,            name="hr_payslip_edit"),

    # Salary Setups
    path("hr/salary/setups/",                           views.hr_salary_setups,           name="hr_salary_setups"),
    path("hr/salary/setups/add/",                       views.hr_salary_setup_edit,       name="hr_salary_setup_add"),
    path("hr/salary/setups/<int:pk>/",                  views.hr_salary_setup_edit,       name="hr_salary_setup_edit"),
    path("hr/salary/setups/<int:pk>/delete/",           views.hr_salary_setup_delete,     name="hr_salary_setup_delete"),
    path("hr/salary/calculate/",                        views.hr_salary_calculate,        name="hr_salary_calculate"),
    path("hr/salary/forecast/",                         views.hr_salary_forecast,         name="hr_salary_forecast"),

    # Statutory Deductions
    path("hr/salary/statutory/",                        views.hr_statutory_deductions,    name="hr_statutory_deductions"),
    path("hr/salary/statutory/add/",                    views.hr_statutory_deduction_edit,name="hr_statutory_deduction_add"),
    path("hr/salary/statutory/<int:pk>/",               views.hr_statutory_deduction_edit,name="hr_statutory_deduction_edit"),
    path("hr/salary/statutory/<int:pk>/delete/",        views.hr_statutory_deduction_delete, name="hr_statutory_deduction_delete"),

    # Tax Years
    path("hr/salary/tax-years/",                        views.hr_tax_years,               name="hr_tax_years"),
    path("hr/salary/tax-years/add/",                    views.hr_tax_year_edit,           name="hr_tax_year_add"),
    path("hr/salary/tax-years/<int:pk>/",               views.hr_tax_year_edit,           name="hr_tax_year_edit"),
    path("hr/salary/tax-years/<int:pk>/delete/",        views.hr_tax_year_delete,         name="hr_tax_year_delete"),
    path("hr/salary/tax-years/<int:tax_year_pk>/slabs/add/",  views.hr_tax_slab_inline_add,    name="hr_tax_slab_inline_add"),
    path("hr/salary/tax-slabs/<int:pk>/update/",             views.hr_tax_slab_inline_update, name="hr_tax_slab_inline_update"),
    path("hr/salary/tax-slabs/<int:pk>/delete/",             views.hr_tax_slab_inline_delete, name="hr_tax_slab_inline_delete"),

    # Attendance extras
    path("hr/attendance/policies/",                     views.hr_attendance_policy,       name="hr_attendance_policy"),
    path("hr/attendance/device-employees/",             views.hr_device_employees,        name="hr_device_employees"),
    path("hr/attendance/device-employees/add/",         views.hr_device_employee_edit,    name="hr_device_employee_add"),
    path("hr/attendance/device-employees/<int:pk>/",    views.hr_device_employee_edit,    name="hr_device_employee_edit"),
    path("hr/attendance/device-employees/<int:pk>/delete/", views.hr_device_employee_delete, name="hr_device_employee_delete"),
    path("hr/attendance/sync-schedules/",               views.hr_sync_schedules,          name="hr_sync_schedules"),
    path("hr/attendance/sync-schedules/fetch/",         views.hr_sync_schedule_fetch,     name="hr_sync_schedule_fetch"),
    path("hr/attendance/sync-schedules/add/",           views.hr_sync_schedule_edit,      name="hr_sync_schedule_add"),
    path("hr/attendance/sync-schedules/<int:pk>/",      views.hr_sync_schedule_edit,      name="hr_sync_schedule_edit"),
    path("hr/attendance/sync-schedules/<int:pk>/delete/", views.hr_sync_schedule_delete,  name="hr_sync_schedule_delete"),

    # WFH
    path("hr/wfh/policy/",                             views.hr_wfh_policy,              name="hr_wfh_policy"),
    path("hr/wfh/days/",                               views.hr_wfh_days,                name="hr_wfh_days"),
    path("hr/wfh/days/<int:pk>/delete/",               views.hr_wfh_day_delete,          name="hr_wfh_day_delete"),
    path("hr/wfh/balances/",                           views.hr_wfh_balances,            name="hr_wfh_balances"),
    path("hr/wfh/balances/<int:employee_pk>/edit/",    views.hr_wfh_balance_edit,        name="hr_wfh_balance_edit"),

    # Leave Types & Allocations
    path("hr/leaves/types/",                            views.hr_leave_types,             name="hr_leave_types"),
    path("hr/leaves/types/add/",                        views.hr_leave_type_edit,         name="hr_leave_type_add"),
    path("hr/leaves/types/<int:pk>/",                   views.hr_leave_type_edit,         name="hr_leave_type_edit"),
    path("hr/leaves/types/<int:pk>/delete/",            views.hr_leave_type_delete,       name="hr_leave_type_delete"),
    path("hr/leaves/allocations/",                      views.hr_leave_allocations,       name="hr_leave_allocations"),
    path("hr/leaves/allocations/add/",                  views.hr_leave_allocation_edit,   name="hr_leave_allocation_add"),
    path("hr/leaves/allocations/<int:pk>/",             views.hr_leave_allocation_edit,   name="hr_leave_allocation_edit"),
    path("hr/leaves/allocations/<int:pk>/delete/",      views.hr_leave_allocation_delete, name="hr_leave_allocation_delete"),

    # Teams
    path("hr/teams/",                                   views.hr_teams,                   name="hr_teams"),
    path("hr/teams/add/",                               views.hr_team_edit,               name="hr_team_add"),
    path("hr/teams/<int:pk>/",                          views.hr_team_edit,               name="hr_team_edit"),
    path("hr/teams/<int:pk>/delete/",                   views.hr_team_delete,             name="hr_team_delete"),
    path("hr/teams/members/",                           views.hr_team_members,            name="hr_team_members"),
    path("hr/teams/members/add/",                       views.hr_team_member_edit,        name="hr_team_member_add"),
    path("hr/teams/members/<int:pk>/",                  views.hr_team_member_edit,        name="hr_team_member_edit"),
    path("hr/teams/members/<int:pk>/delete/",           views.hr_team_member_delete,      name="hr_team_member_delete"),
    path("hr/teams/<int:team_pk>/members/add/",         views.hr_team_member_inline_add,  name="hr_team_member_inline_add"),
    path("hr/teams/members/<int:pk>/update/",           views.hr_team_member_inline_update, name="hr_team_member_inline_update"),
    path("hr/teams/members/<int:pk>/remove/",           views.hr_team_member_inline_remove, name="hr_team_member_inline_remove"),

    # Users
    path("hr/users/",                                   views.hr_users,                   name="hr_users"),
    path("hr/users/add/",                               views.hr_user_edit,               name="hr_user_add"),
    path("hr/users/<int:pk>/",                          views.hr_user_edit,               name="hr_user_edit"),
    path("hr/users/<int:pk>/delete/",                   views.hr_user_delete,             name="hr_user_delete"),
]
