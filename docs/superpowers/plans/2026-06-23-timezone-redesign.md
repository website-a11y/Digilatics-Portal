# Timezone Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make attendance check-in/out times correct and stable by interpreting device punches through an explicit, admin-set Device Timezone, never letting the server change the device clock, and bucketing overnight shifts onto the right workday.

**Architecture:** A punch is an instant. Ingestion interprets the device's naive timestamp in the configured **Device TZ**, converts to the storage zone, and assigns a **workday** using a noon cutoff so overnight shifts stay on the check-in day. Display converts to the configured **Display TZ**. The handshake no longer sends any `TimeZone` directive.

**Tech Stack:** Django, SQLite, `zoneinfo`, pyzk/ADMS push.

## Global Constraints

- **Verification environment:** No local Django/DB. Verify each task with `python -m py_compile <files>` and code review; functional verification is a prod smoke-test after deploy. (No pytest suite is assumed runnable here.)
- Device TZ and Display TZ are independent; both selectable from the Pakistan+USA zone set: `Asia/Karachi`, `America/New_York`, `America/Chicago`, `America/Denver`, `America/Los_Angeles`, `America/Phoenix`, `America/Anchorage`, `Pacific/Honolulu`, `UTC`.
- Shifts are overnight (3pm–12am, 4pm–1am, 5pm–2am PKT). First punch = check-in, last = check-out.
- Workday boundary: noon (device-local), configurable.
- Do NOT change the device clock from the server (no `TimeZone=` in the handshake).
- Phase 1 keeps the existing storage (naive ET `TimeField`); it is shippable and reversible on its own. Phase 2 (UTC `DateTimeField`) is separate and only done on explicit go-ahead.

---

## PHASE 1 — Correct ingestion + stable device clock (no schema change)

### Task 1: Device Timezone setting

**Files:**
- Modify: `attendance/models.py` (SystemSetting — add `device_timezone`, getter)
- Create: `attendance/migrations/0016_systemsetting_device_timezone.py`

**Interfaces:**
- Produces: `SystemSetting.get_device_timezone() -> str` (IANA name, default `"Asia/Karachi"`); `SystemSetting.DEVICE_TZ_CHOICES`.

- [ ] **Step 1: Add the field + choices + getter**

```python
# In SystemSetting, reuse TIMEZONE_CHOICES for both selectors.
device_timezone = models.CharField(
    max_length=100,
    choices=TIMEZONE_CHOICES,
    default="Asia/Karachi",
    verbose_name="Device Timezone",
    help_text=(
        "The timezone the biometric device's clock is set to. Punch timestamps "
        "are interpreted in this zone. Must match the device's actual clock."
    ),
)
```

```python
@classmethod
def get_device_timezone(cls) -> str:
    try:
        return cls.get().device_timezone or "Asia/Karachi"
    except Exception:
        return "Asia/Karachi"
```

- [ ] **Step 2: Write the migration** (AddField mirroring the model field, dependency `0015_systemsetting_payroll_cycle_start_day`).

- [ ] **Step 3: Verify** `python -m py_compile attendance/models.py attendance/migrations/0016_systemsetting_device_timezone.py`

- [ ] **Step 4: Commit** `feat: add admin-configurable Device Timezone setting`

---

### Task 2: Shared ingestion helper

**Files:**
- Create: `attendance/ingest.py`

**Interfaces:**
- Produces:
  - `device_tz() -> ZoneInfo` (from `SystemSetting.get_device_timezone()`)
  - `to_store_time(naive_dt) -> (time, date_workday)` — interprets `naive_dt` in device tz, returns the stored ET time and the workday date.
  - `workday_for(aware_local_dt, boundary_hour=12) -> date` — device-local date, rolling pre-boundary punches back one day.
  - `group_punches(punches) -> dict[(emp_pk, workday)] -> {check_in, check_out, count}` — sort by absolute instant; first=in, last=out.

- [ ] **Step 1: Implement `workday_for`** — `local = aware.astimezone(device_tz()); return local.date() - (1 day if local.hour < boundary else 0)`.
- [ ] **Step 2: Implement `to_store_time`** — make `naive_dt` aware in device tz, `localtime()` to ET, return `(et_time, workday_for(aware))`.
- [ ] **Step 3: Implement `group_punches`** — accept list of `(emp_pk, aware_dt)`, bucket by `(emp_pk, workday)`, sort each bucket by the aware instant, derive in/out.
- [ ] **Step 4: Verify** `python -m py_compile attendance/ingest.py`
- [ ] **Step 5: Commit** `feat: shared attendance ingestion helper (device tz + workday bucketing)`

---

### Task 3: Route ADMS + importers through the helper

**Files:**
- Modify: `attendance/views.py` (`_adms_receive_logs`) — use `ingest` helper, drop `settings.ZK_DEVICE['device_timezone']` in favor of the setting.
- Modify: `attendance/management/commands/import_attendance_from_log.py`
- Modify: `attendance/management/commands/import_attendance_csv.py`
- Modify: `attendance/management/commands/sync_device_attendance.py`

**Interfaces:**
- Consumes: Task 2 helpers.

- [ ] **Step 1:** Replace each entry point's inline tz/bucketing with `ingest.workday_for` + `ingest.to_store_time`, keeping the existing upsert + leave/holiday guards. Keep the `--device-tz` override on the log importer (now defaults to the setting).
- [ ] **Step 2: Verify** `python -m py_compile` on all four files.
- [ ] **Step 3: Commit** `refactor: unify attendance ingestion on shared helper`

---

### Task 4: Stop the handshake from changing the device clock

**Files:**
- Modify: `attendance/views.py` (`_adms_handshake`) — remove the `TimeZone=...` line from the response body; update docstring.

- [ ] **Step 1:** Delete the `"TimeZone=-8\n"` (or current) line from the handshake body.
- [ ] **Step 2:** Add a comment: device clock is set on the device; server never overrides it.
- [ ] **Step 3: Verify** `python -m py_compile attendance/views.py`
- [ ] **Step 4: Commit** `fix: handshake no longer overrides the device clock`

---

### Task 5: Device Timezone in Settings UI

**Files:**
- Modify: `portal/views.py` (`hr_settings`) — save `device_timezone`.
- Modify: `templates/portal/hr/settings.html` — add a Device Timezone selector.

- [ ] **Step 1:** In `hr_settings` POST, validate `device_timezone` against the choices and save.
- [ ] **Step 2:** Add a selector card mirroring the Display Timezone one.
- [ ] **Step 3: Verify** `python -m py_compile portal/views.py`
- [ ] **Step 4: Commit** `feat: Device Timezone selector on Settings page`

---

### Task 6 (verification): prod smoke-test checklist

- [ ] Deploy: push → `git pull` → `migrate` → restart.
- [ ] Settings shows Device TZ (Asia/Karachi) + Display TZ; both save.
- [ ] Device clock: set it once on the device; confirm it is NOT reset after a poll.
- [ ] A fresh punch appears with the correct PKT time on the right workday.
- [ ] An overnight shift (e.g. 4pm→1am) shows in=~4pm, out=~1am on the **start** day.

---

## PHASE 2 — UTC datetime storage (separate, only on explicit go-ahead)

> Heavy, untestable-without-a-running-app, touches every display site. Do as its own
> carefully-executed effort (ideally with a runnable env), not bundled with Phase 1.

Outline (each becomes a task when greenlit):
1. Schema: `check_in`/`check_out` `TimeField` → `DateTimeField` (UTC, aware); keep `date` as workday.
2. Data migration: combine `date`+naive time as ET → UTC datetime (lossless, preserves current display).
3. `tz_utils`: single helper converting a stored UTC datetime → Display TZ; `tz_time` filter accepts a datetime.
4. Update every display site (portal attendance, dashboard, manager/HR views, admin, Excel exports) to pass the datetime.
5. Ingestion writes UTC datetimes via the Task 2 helper.
6. Round-trip + DST + overnight unit checks.

---

## Self-Review

- **Spec coverage:** Device TZ setting (Task 1, 5) ✓; handshake no clock change (Task 4) ✓; decoupled zones (Task 1, 5) ✓; overnight workday bucketing (Task 2) ✓; Pakistan+USA list (Global Constraints) ✓; UTC storage (Phase 2) ✓ deferred by design; payroll explicitly out of scope ✓.
- **Placeholders:** none — verification steps are concrete for this env.
- **Deviation from spec:** spec made UTC storage core; this plan ships the correctness fix in Phase 1 without it (YAGNI + untestable-migration risk) and isolates UTC storage as Phase 2. Flagged for user decision.
