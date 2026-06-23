# Timezone Redesign — Design Spec

**Date:** 2026-06-23
**Status:** Approved (design); pending implementation plan
**Scope:** Attendance punch storage, device-clock handling, and timezone conversion.
**Out of scope:** Payroll cycle (23rd–22nd) — tracked as a separate spec.

---

## 1. Problem

Check-in/out times have repeatedly displayed in the wrong column or shifted by
hours. Every recurrence traces to the same two root causes:

1. **Wall-clock storage with an implicit zone.** `AttendanceRecord.check_in` /
   `check_out` are naive `TimeField`s assumed to be Eastern Time, and conversion
   logic is scattered across views, templates, importers, and exports. Any place
   that assumes the wrong zone — or a time-of-day that crosses midnight — produces
   a wrong or swapped value.
2. **The server moves the device clock.** The ADMS handshake sends a `TimeZone=`
   directive every poll (~1/min), so the device clock kept changing across the
   project's timezone churn. Punches recorded under one clock offset were later
   interpreted under another, corrupting historical data with no single offset to
   undo.

## 2. Guiding principle

**A punch is an instant in time. Store the instant in UTC. Convert only at the
edges (ingestion in, display out).** There is no implicit zone anywhere in the
middle, so there is nothing left to guess wrong.

## 3. The three timezones (fully decoupled)

| Zone | Lives in | Set by | Used for |
|------|----------|--------|----------|
| **Device TZ** | new DB setting `SystemSetting.device_timezone` | admin (must match the device's actual clock) | interpreting incoming naive punch timestamps |
| **Display TZ** | existing `SystemSetting.display_timezone` | admin | rendering all times in the portal/admin/exports |
| **UTC** | the database (`AttendanceRecord.check_in/out`) | automatic | the canonical stored instant |

Device TZ and Display TZ are independent — either may be any zone, and conversion
remains correct. DST and midnight-crossing are handled automatically by `zoneinfo`
because we always work with full datetimes (date + time), never bare times.

## 4. Data flow

### Ingestion (punch in)
```
device sends naive "2026-06-23 16:00:00"      (its own wall clock)
   │  interpret in Device TZ  (e.g. Asia/Karachi)
   ▼
aware 2026-06-23 16:00:00+05:00
   │  normalize to UTC
   ▼
store check_in = 2026-06-23 11:00:00+00:00     (UTC, tz-aware DateTimeField)
   │  workday = assign_workday(aware_local)     (see §6)
   ▼
AttendanceRecord(date=<workday>, check_in=<UTC dt>, check_out=<UTC dt>)
```

### Display (punch out to screen)
```
stored UTC datetime  ──convert to Display TZ──▶  "4:00 PM"  (any zone the admin picks)
```

## 5. Schema change — `AttendanceRecord`

- `check_in`: `TimeField` (naive ET) → **`DateTimeField(null=True, blank=True)`** storing a tz-aware UTC instant.
- `check_out`: same change.
- `date`: **unchanged** — remains the canonical **workday** (a `DateField`), used for
  grouping, `unique_together("employee", "date")`, and queries.
- `is_late` / `is_early_checkout`: still booleans; computed by comparing the punch
  instant (converted to the schedule's reference zone) against the employee's
  scheduled times. Logic moves into the shared service helper.

## 6. Workday assignment (overnight shifts)

Shifts are **3 PM→12 AM, 4 PM→1 AM, 5 PM→2 AM** — all cross midnight in PKT, so a
shift's check-out falls on the next calendar day. Bucketing each punch by its own
calendar date would split one shift into two records.

**Rule:** assign every punch to a workday using a **day-boundary cutoff**
(default **12:00 noon, device-local**), stored as a setting
`SystemSetting.workday_start_hour` (default 12):

- Punch local time **≥ cutoff** → workday = that device-local date.
- Punch local time **< cutoff** → workday = **previous** device-local date.

Because all shifts start in the afternoon (≥15:00) and end by 02:00, the noon
boundary cleanly groups each shift's punches onto the **check-in's day**. Within a
workday group, punches are sorted by absolute UTC instant: **first = check-in,
last = check-out** (single punch → check-in only, check-out null).

## 7. Handshake change (device clock is never touched)

- **Remove the `TimeZone=` line from `_adms_handshake` entirely.** The server stops
  writing the device clock. The admin sets the device's time/zone on the device; it
  stays put.
- Add a regression test asserting the handshake response body contains **no**
  `TimeZone` directive, so this cannot silently come back.
- Operational note (documented for admins): the **Device TZ setting must match the
  device's actual clock zone**. If the device's clock zone is changed, update the
  setting to match.

## 8. Settings UI ("show all timezones")

- Add a **Device Timezone** dropdown alongside the existing **Display Timezone** on
  the System Settings screen.
- Both dropdowns list the **Pakistan + USA** zone set:
  `Asia/Karachi (PKT)`, `America/New_York (ET)`, `America/Chicago (CT)`,
  `America/Denver (MT)`, `America/Los_Angeles (PT)`, `America/Phoenix (AZ, no DST)`,
  `America/Anchorage (AK)`, `Pacific/Honolulu (HI)`, `UTC`.
- `device_timezone` moves **out of `settings.py`** into the DB setting so it is
  editable without a deploy. (`settings.ZK_DEVICE` keeps host/port/etc. only.)
- Add `workday_start_hour` to the same settings screen (default 12).

## 9. Ingestion — one shared code path

All three entry points call **one helper module** so behaviour is identical:

- live ADMS handler (`attendance/views.py::_adms_receive_logs`)
- `import_attendance_from_log`
- `import_attendance_csv`

Shared helper responsibilities:
1. `to_utc(naive_device_dt) -> aware UTC` using the Device TZ setting.
2. `assign_workday(aware_local_dt) -> date` using the workday cutoff.
3. Group punches by `(employee, workday)`, sort by absolute UTC instant, derive
   check-in/check-out, compute late/early flags, upsert the record.

The historical `--device-tz` override on `import_attendance_from_log` is retained
for reconstructing pre-cutover eras (see §11).

## 10. Display — one conversion helper

`attendance/tz_utils.py` becomes the single place conversion lives. It exposes a
helper that takes a stored UTC datetime and returns it formatted in the Display TZ.
Every display site uses it:

- portal attendance, dashboard, manager views, HR views
- Django admin (list + detail)
- Excel/CSV exports

A template filter (`tz_time`) wraps the helper for templates. Leave times,
short-leave, and other displayed times continue to use the same helper, so they
follow the Display TZ automatically.

## 11. Migration & historical correction (two clean steps)

**Step A — schema migration (mechanical, lossless).**
Convert each existing `check_in/out` `TimeField` value to a UTC `DateTimeField`:
combine the record's `date` + the naive time, interpret as the **legacy storage
zone (America/New_York)**, normalize to UTC. This preserves existing values exactly
as they display today (no behavioural change from the migration alone).

**Step B — history reconstruction (validated, separate).**
Re-run `import_attendance_from_log` per device-clock era to fix the historically
wrong days, now writing the clean UTC schema:
- device clock = **UTC** for punches before ~2026-06-15 (`--device-tz UTC`)
- device clock = **UTC-8** for punches on/after the cutover
Validated by `--dry-run --show-emp` against a known 3 PM–12 AM shift before writing.
Limited by log coverage (back to ~Feb 9; incomplete days won't gain a check-out).

## 12. Testing

- **Unit:** `to_utc`, `assign_workday` (incl. each overnight shift + the noon
  boundary), check-in/out derivation from sorted punches, late/early flags.
- **Round-trip:** punch in Device TZ → store UTC → display in Display TZ returns the
  original wall time, for several Device/Display zone combinations (PKT↔ET, etc.).
- **Regression:** handshake body contains no `TimeZone` directive.
- **DST/midnight:** a 4 PM→1 AM shift groups onto one workday; a shift around a DST
  transition converts correctly.

## 13. Non-goals / explicitly unchanged

- Payroll cycle (23rd–22nd) — separate spec.
- ZKTeco device hardware configuration — admin sets the device clock manually.
- The `date`/workday concept and `unique_together` constraint — kept as-is.
