# Attendance history rebuild — runbook

Self-contained procedure for correcting historical attendance that was stored
with the wrong timezone, after the biometric device clock was changed across
migration eras (UTC → UTC-8 → PKT).

**Everything here is safe to read/dry-run. Nothing writes until you pass `--apply`.**

## Background (why this is needed)

Employees are in Pakistan and work afternoon/overnight shifts (check-in ~16:00
PKT, check-out ~01:00 PKT the next day). The device records whatever its own
clock says. That clock's UTC offset was changed several times, so the same
9-to-5-equivalent punch reads as a *different* time-of-day depending on when it
happened:

| Device clock era | A 16:00 PKT check-in reads as | A 01:00 PKT check-out reads as |
|---|---|---|
| PKT (UTC+5) | 16:00 | 01:00 (next day) |
| UTC (UTC+0) | 11:00 | 20:00 (same day) |
| UTC-8 | 03:00 | 12:00 (same day) |

History processed with one fixed timezone mis-converted the eras it didn't
match. The current live pipeline is correct; only old records are affected.

## Step 1 — Confirm the source data exists

The rebuild reads `zkteco_debug.log` (the device pushed every punch; ZK full
re-dumps mean it should hold the full history). From the project dir, in the
venv:

```bash
python manage.py diagnose_punch_eras --log zkteco_debug.log
```

Check the printed **date range** covers the period you need corrected. If the
log was rotated/truncated, locate the full copy and pass it with `--log`.

## Step 2 — Find the era boundaries

```bash
# Pick 2–3 employees who worked regularly across the whole period.
# Use their DEVICE id (DeviceEmployee.device_user_id), not the employee pk.
python manage.py diagnose_punch_eras --emp <deviceId1> --emp <deviceId2>
```

In each employee's day-by-day list, find the **date where their whole daily
pattern jumps**. The value it jumps to tells you the device clock zone for that
era (compare against the table above — e.g. check-ins landing around 03:00 ⇒
UTC-8; around 11:00 ⇒ UTC; around 16:00 ⇒ PKT). Note the boundary date(s) and
the zone before/after each.

> The global "DAILY EARLIEST-PUNCH HOUR" table is only a rough hint (overnight
> check-outs pollute it). Trust the per-employee view.

## Step 3 — Dry-run + spot-check (writes nothing)

Translate the boundaries into flags. `--base-tz` is the zone *before* the first
boundary; each `--era YYYY-MM-DD:ZONE` is the zone *on/after* that date.

```bash
# EXAMPLE ONLY — replace dates/zones with what Step 2 showed:
python manage.py rebuild_attendance_history \
    --base-tz UTC \
    --era 2026-06-19:UTC-8 \
    --era 2026-06-23:Asia/Karachi \
    --emp <deviceId1> --emp <deviceId2>
```

Zone tokens accept IANA names (`Asia/Karachi`) or fixed offsets (`UTC`,
`UTC-8`, `UTC+5`). Review the `OLD → NEW` table: spot-check a few `NEW` values
against the raw punch lines for that employee/date in the log.

Narrow the window while validating with `--from YYYY-MM-DD --to YYYY-MM-DD`.

## Step 4 — Apply

Only after the comparison looks right:

```bash
# BACK UP THE DATABASE FIRST.
python manage.py rebuild_attendance_history \
    --base-tz UTC --era 2026-06-19:UTC-8 --era 2026-06-23:Asia/Karachi \
    --apply
```

## Safety notes

- **Back up the DB before `--apply`.**
- A full rebuild **overwrites manual time edits** in the affected range. Records
  tied to a leave request or public holiday are **never** touched; manual punch
  corrections are not protected — narrow with `--from/--to` to avoid them.
- The current PKT era needs no correction; you can stop `--to` at the day before
  the device went to PKT if you only want to fix the broken eras.
- Re-running is idempotent: rows already correct report as `unchanged`.
