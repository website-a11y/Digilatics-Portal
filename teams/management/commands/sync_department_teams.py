"""
Management command: sync_department_teams

Reads every unique department value from EmployeeProfile and ensures:
  1. A Team exists with that name (creates one if missing).
  2. The team manager is set to an active MANAGER-role employee in that dept.
  3. Every active employee in the dept who reports to that manager is enrolled
     as a TeamMember.

Usage:
    python manage.py sync_department_teams [--dry-run]
"""

from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count, Q

from accounts.models import EmployeeProfile
from teams.models import Team, TeamMember


class Command(BaseCommand):
    help = "Create teams from existing department values and enrol employees as members."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would happen without making any changes.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes will be saved.\n"))

        # All active employees with a non-blank department
        active_qs = EmployeeProfile.objects.filter(
            employment_status__in=[
                EmployeeProfile.EmploymentStatusChoices.ACTIVE,
                EmployeeProfile.EmploymentStatusChoices.ONBOARDING,
                EmployeeProfile.EmploymentStatusChoices.ON_LEAVE,
            ],
        ).exclude(department="").select_related("reporting_manager")

        departments = (
            active_qs.values_list("department", flat=True)
            .distinct()
            .order_by("department")
        )

        teams_created = 0
        teams_updated = 0
        members_created = 0
        skipped_depts = []

        for dept_name in departments:
            dept_employees = active_qs.filter(department=dept_name)

            # ── Find best manager ──────────────────────────────────────────────
            # 1st choice: MANAGER-role employee in the same department.
            manager_role_candidates = dept_employees.filter(
                role=EmployeeProfile.RoleChoices.MANAGER,
                employment_status=EmployeeProfile.EmploymentStatusChoices.ACTIVE,
            )

            needs_role_fix = False

            if manager_role_candidates.exists():
                manager_pool = manager_role_candidates
            else:
                # 2nd choice: most common reporting_manager for this department
                # (any active employee — role will need fixing manually).
                rm_count = (
                    dept_employees.exclude(reporting_manager=None)
                    .values("reporting_manager_id")
                    .annotate(n=Count("reporting_manager_id"))
                    .order_by("-n")
                    .first()
                )
                if rm_count:
                    candidate = EmployeeProfile.objects.filter(
                        pk=rm_count["reporting_manager_id"],
                        employment_status=EmployeeProfile.EmploymentStatusChoices.ACTIVE,
                    ).first()
                    manager_pool = (
                        EmployeeProfile.objects.filter(pk=candidate.pk)
                        if candidate else EmployeeProfile.objects.none()
                    )
                else:
                    # 3rd choice: first active employee in the department
                    manager_pool = dept_employees.filter(
                        employment_status=EmployeeProfile.EmploymentStatusChoices.ACTIVE,
                    )
                needs_role_fix = True

            if not manager_pool.exists():
                skipped_depts.append(
                    f"  {dept_name!r} — no active employee found at all, skipped."
                )
                continue

            # Among candidates, pick the one who is reporting_manager for most dept employees
            best_manager = (
                manager_pool
                .annotate(
                    reports_in_dept=Count(
                        "team_members",
                        filter=Q(team_members__department=dept_name),
                    )
                )
                .order_by("-reports_in_dept", "full_name")
                .first()
            )
            if not best_manager:
                best_manager = manager_pool.first()

            if needs_role_fix:
                skipped_depts.append(
                    f"  {dept_name!r} — assigned {best_manager.full_name!r} as manager "
                    f"but their role is not 'Manager'. "
                    f"Update their role in Employee Registrations."
                )

            # ── Create / update Team ───────────────────────────────────────────
            team = Team.objects.filter(name=dept_name).first()

            if team is None:
                code = _make_code(dept_name)
                if dry_run:
                    self.stdout.write(
                        f"  [CREATE] Team {dept_name!r}  code={code!r}  "
                        f"manager={best_manager.full_name}"
                    )
                else:
                    with transaction.atomic():
                        team = Team(
                            name=dept_name,
                            code=code,
                            department=dept_name,
                            manager=best_manager,
                            is_active=True,
                        )
                        team.save()
                teams_created += 1
            else:
                changed = False
                if team.manager_id != best_manager.pk:
                    if not dry_run:
                        team.manager = best_manager
                        changed = True
                if not team.department:
                    if not dry_run:
                        team.department = dept_name
                        changed = True
                if changed and not dry_run:
                    with transaction.atomic():
                        team.save()
                teams_updated += 1
                if dry_run:
                    self.stdout.write(
                        f"  [EXISTS] Team {dept_name!r}  "
                        f"manager={best_manager.full_name}"
                    )

            if dry_run or team is None:
                # Count potential new members
                potential = dept_employees.filter(
                    reporting_manager=best_manager,
                ).exclude(pk=best_manager.pk).count()
                self.stdout.write(f"           → {potential} employee(s) would be enrolled")
                continue

            # ── Enrol members ──────────────────────────────────────────────────
            # Add all active employees whose reporting_manager is this team's manager.
            enrolees = dept_employees.filter(
                reporting_manager=best_manager,
            ).exclude(pk=best_manager.pk)

            today = date.today()
            for emp in enrolees:
                already_has_primary = TeamMember.objects.filter(
                    employee=emp, is_primary=True
                ).exists()

                member, created = TeamMember.objects.get_or_create(
                    team=team,
                    employee=emp,
                    defaults={
                        "role_in_team": TeamMember.TeamRoleChoices.MEMBER,
                        "joined_at": emp.joining_date or today,
                        "is_primary": not already_has_primary,
                    },
                )
                if created:
                    members_created += 1

        # ── Summary ───────────────────────────────────────────────────────────
        self.stdout.write("")
        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"DRY RUN complete — no changes written.\n"
                f"  Teams to create  : {teams_created}\n"
                f"  Teams to update  : {teams_updated}\n"
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Sync complete.\n"
                f"  Teams created : {teams_created}\n"
                f"  Teams updated : {teams_updated}\n"
                f"  Members added : {members_created}\n"
            ))

        if skipped_depts:
            self.stdout.write(self.style.WARNING(
                "Departments needing attention:"
            ))
            for line in skipped_depts:
                self.stdout.write(self.style.WARNING(line))


def _make_code(name: str) -> str:
    """Generate a short unique code from a department name."""
    import re
    base = re.sub(r"[^A-Za-z0-9]", "", name).upper()[:8] or "TEAM"
    code = base
    counter = 1
    while Team.objects.filter(code=code).exists():
        suffix = str(counter)
        code = base[: 8 - len(suffix)] + suffix
        counter += 1
    return code
