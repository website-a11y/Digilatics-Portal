"""
Attendance views:
  - ZKTeco ADMS push protocol  (/iclock/*)
  - Employee self-punch portal  (/punch/)
"""
from datetime import datetime, timezone as dt_timezone
import logging
import os

from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import AttendanceRecord, DeviceEmployee, DeviceSyncFlag

logger = logging.getLogger("attendance.zkteco")


def _adms_flag_dir():
    # Use /tmp so the web-server process always has write permission.
    # Fall back to the project-local directory only if /tmp is unavailable.
    tmp = "/tmp/funnelatics_adms_flags"
    try:
        os.makedirs(tmp, exist_ok=True)
        # Quick write test
        test = os.path.join(tmp, ".write_test")
        with open(test, "w") as f:
            f.write("ok")
        os.remove(test)
        return tmp
    except OSError:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "adms_flags")
        os.makedirs(path, exist_ok=True)
        return path


def _adms_force_path(sn="all"):
    return os.path.join(_adms_flag_dir(), f".zk_force_query_{sn}")


def _adms_queried_path(sn):
    return os.path.join(_adms_flag_dir(), f".zk_queried_{sn}")


def force_adms_data_query(sn=None):
    file_path = _adms_force_path(sn or "all")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("force")


def _should_force_query(sn):
    all_path = _adms_force_path("all")
    sn_path = _adms_force_path(sn)
    if os.path.exists(all_path):
        os.remove(all_path)
        return True
    if os.path.exists(sn_path):
        os.remove(sn_path)
        return True
    return False


# ════════════════════════════════════════════════════════════════════════════════
# ZKTeco ADMS push protocol
#
# The device is configured with:
#   Server IP   = this server's LAN IP (e.g. 192.168.1.x)
#   Server Port = 8000  (or 80 in production)
#   HTTPS       = No
#
# Device lifecycle:
#   1. GET  /iclock/cdata?SN=<serial>&options=all  → server returns config
#   2. POST /iclock/cdata?SN=<serial>&table=ATTLOG → server receives punches
#   3. GET  /iclock/getrequest?SN=<serial>         → server returns pending cmds
#   4. POST /iclock/devicecmd?SN=<serial>          → device acks commands
# ════════════════════════════════════════════════════════════════════════════════

# Punch-status codes the device sends
_PUNCH_IN  = {0, 4}   # 0=Check-In  4=OT-In
_PUNCH_OUT = {1, 2, 3, 5}  # 1=Check-Out  2=Break-Out  3=OT-Out  5=Break-In


@csrf_exempt
def iclock_cdata(request):
    """
    GET  → device heartbeat / initial registration
    POST → device uploads attendance log (ATTLOG)
    """
    # Debug: log to /tmp so the web-server process always has write access
    import os
    log_path = "/tmp/funnelatics_zkteco_debug.log"
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"METHOD: {request.method}\n")
            f.write(f"PATH: {request.get_full_path()}\n")
            f.write(f"FROM: {request.META.get('REMOTE_ADDR')}\n")
            f.write(f"CONTENT-TYPE: {request.content_type}\n")
            body = request.body.decode("utf-8", errors="replace")
            f.write(f"BODY ({len(body)} bytes):\n{body[:3000]}\n")
    except OSError:
        pass

    if request.method == "GET":
        return _adms_handshake(request)
    if request.method == "POST":
        return _adms_receive_logs(request)
    return HttpResponse(status=405)


def _adms_handshake(request):
    """
    Respond to device check-in with server config.
    Normally ATTLOGStamp=9999 prevents the device from bulk-uploading old
    records on every handshake.
    When a full_sync_from flag exists we return ATTLOGStamp=0 instead so the
    device immediately re-uploads ALL its stored punches (more reliable than
    DATA QUERY on most ZKTeco models).
    TransInterval=1 keeps the device polling every minute for new commands.
    TimeZone=0 instructs the device to send timestamps in UTC so we can
    reliably convert to Eastern Time on the server side.
    """
    sn = request.GET.get("SN", "unknown")
    logger.info("ADMS handshake from device SN=%s", sn)

    # Check if a full re-sync was requested (set by reset_and_resync command).
    # Use ATTLOGStamp=0 to tell device "send all stored punches from scratch".
    # NOTE: only PEEK here — iclock_getrequest consumes the flag to send a wide
    # DATA QUERY covering the historical range. Clearing it here would race
    # getrequest and limit the device to only the last 2 days.
    # ZK_FETCH_FROM (settings) forces a full re-dump on every poll — used for a
    # one-time historical recovery; set it, recover, then set back to None.
    if getattr(settings, "ZK_FETCH_FROM", None) or DeviceSyncFlag.peek():
        att_stamp = "0"
        logger.info("ADMS: full-sync handshake (ATTLOGStamp=0) for SN=%s", sn)
    else:
        att_stamp = "9999"

    body = (
        f"GET OPTION FROM: {sn}\n"
        f"ATTLOGStamp={att_stamp}\n"
        "OPERLOGStamp=9999\n"
        "ATTPHOTOStamp=None\n"
        "ErrorDelay=30\n"
        "Delay=1\n"
        "TransTimes=00:00;23:59\n"
        "TransInterval=1\n"
        "TransFlag=TransData AttLog\n"
        "TimeZone=-8\n"
        "Realtime=1\n"
        "Encrypt=None\n"
    )
    return HttpResponse(body, content_type="text/plain")


def _adms_receive_logs(request):
    """
    Parse the device's ATTLOG POST body and write AttendanceRecords.

    Body format (tab-separated lines after the header):
        table=ATTLOG&Stamp=9999
        UID\\tBIO_ID\\tATT_TIME\\tSTATUS\\tVERIFY\\tWORK_CODE\\t...
        1\\t10001\\t2026-05-12 09:00:00\\t0\\t1\\t\\t
        2\\t10002\\t2026-05-12 09:05:00\\t1\\t1\\t\\t
    """
    sn = request.GET.get("SN", "unknown")
    raw = request.body.decode("utf-8", errors="replace")
    logger.debug("ADMS log upload SN=%s body:\n%s", sn, raw[:2000])

    lines = [l for l in raw.splitlines() if l.strip()]
    if not lines:
        return HttpResponse("OK: 0", content_type="text/plain")

    # Skip the header line (table=ATTLOG&...)
    data_lines = [l for l in lines if not l.startswith("table=")]

    # Pre-load device mappings
    mappings = {
        dm.device_user_id: dm.employee
        for dm in DeviceEmployee.objects.select_related("employee").all()
    }

    from collections import defaultdict
    # Collect all punches grouped by (employee, date)
    punches: dict = defaultdict(list)  # (emp_pk, date) → [(time, status_code)]
    unknown_ids = set()

    # Stray device enrollments with no real employee (e.g. test/duplicate IDs).
    # Their punches are dropped silently instead of logged as "unmapped".
    ignored_ids = {int(x) for x in getattr(settings, "ZK_IGNORED_DEVICE_IDS", [])}

    for line in data_lines:
        parts = line.split("\t")
        if len(parts) < 2:
            continue

        # Two formats exist:
        #   New (no UID prefix): BIO_ID  ATT_TIME  VERIFY  STATUS  ...
        #   Old (with UID):      UID     BIO_ID    ATT_TIME STATUS  ...
        # Detect by checking if parts[1] looks like a timestamp
        if len(parts) >= 2 and " " in parts[1] and ":" in parts[1]:
            # New format: parts[0]=BIO_ID, parts[1]=ATT_TIME, parts[2]=VERIFY, parts[3]=STATUS
            bio_id_str = parts[0].strip()
            att_time_str = parts[1].strip()
            status_code = int(parts[3].strip()) if len(parts) > 3 and parts[3].strip().lstrip("-").isdigit() else 0
        else:
            # Old format: parts[0]=UID, parts[1]=BIO_ID, parts[2]=ATT_TIME, parts[3]=STATUS
            bio_id_str = parts[1].strip()
            att_time_str = parts[2].strip()
            status_code = int(parts[3].strip()) if len(parts) > 3 and parts[3].strip().lstrip("-").isdigit() else 0

        try:
            device_uid = int(bio_id_str)
        except ValueError:
            continue

        employee = mappings.get(device_uid)
        if employee is None:
            if device_uid not in ignored_ids:
                unknown_ids.add(device_uid)
            continue

        punch_dt = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
            try:
                punch_dt = datetime.strptime(att_time_str, fmt)
                break
            except ValueError:
                continue
        if punch_dt is None:
            logger.warning("ADMS: unrecognised timestamp %r", att_time_str)
            continue

        # Device clock is set to PST (America/Los_Angeles) and sends naive
        # timestamps in that timezone.  Attach PST, then convert to portal
        # local time (America/New_York / EST) for storage.
        from zoneinfo import ZoneInfo
        punch_dt_pst = timezone.make_aware(punch_dt, ZoneInfo("America/Los_Angeles"))
        punch_dt_local = timezone.localtime(punch_dt_pst)

        punches[(employee.pk, punch_dt_local.date())].append((punch_dt_local.time(), status_code))

    if unknown_ids:
        logger.warning("ADMS: unmapped device IDs %s — add them in Device Employee Mappings", unknown_ids)

    from attendance.services import compute_attendance_flags

    created = updated = skipped = 0
    emp_cache = {dm.device_user_id: dm.employee for dm in DeviceEmployee.objects.select_related("employee")}
    emp_by_pk = {e.pk: e for e in emp_cache.values()}

    from datetime import time as _time, timedelta as _timedelta

    # Overnight-checkout threshold: a single punch arriving before this hour EST
    # is treated as a checkout for the PREVIOUS day's open record rather than a
    # new check-in, provided that previous record has a check-in but no check-out.
    _OVERNIGHT_CUTOFF = _time(8, 0)  # 8:00 AM EST

    for (emp_pk, punch_date), punch_list in punches.items():
        employee = emp_by_pk.get(emp_pk)
        if not employee:
            continue

        punch_list.sort(key=lambda x: x[0])
        times = [t for t, _ in punch_list]

        # Overnight-checkout reassignment:
        # If there is exactly one early-morning punch (<08:00 EST) and the previous
        # calendar day has an open record (check_in set, check_out null), this punch
        # is a late checkout for that shift — not a new check-in for today.
        if (
            len(times) == 1
            and times[0] < _OVERNIGHT_CUTOFF
        ):
            prev_date = punch_date - _timedelta(days=1)
            prev_record = AttendanceRecord.objects.filter(
                employee=employee, date=prev_date,
                status=AttendanceRecord.StatusChoices.PRESENT,
                check_in__isnull=False, check_out__isnull=True,
            ).first()
            if prev_record and not prev_record.leave_request_id:
                prev_record.check_out = times[0]
                flags_prev = compute_attendance_flags(
                    employee, prev_record.check_in, times[0]
                )
                prev_record.is_late = flags_prev["is_late"]
                prev_record.is_early_checkout = flags_prev["is_early_checkout"]
                prev_record.notes = "ZKTeco ADMS (overnight checkout added)"
                prev_record.save(update_fields=[
                    "check_out", "is_late", "is_early_checkout", "notes", "updated_at",
                ])
                logger.info(
                    "ADMS: overnight checkout %s reassigned to %s check_out=%s",
                    employee, prev_date, times[0],
                )
                # Remove any ABSENT placeholder that may have been created for
                # punch_date before the overnight checkout arrived.
                AttendanceRecord.objects.filter(
                    employee=employee,
                    date=punch_date,
                    status=AttendanceRecord.StatusChoices.ABSENT,
                    check_in__isnull=True,
                    leave_request__isnull=True,
                ).delete()
                updated += 1
                continue  # do NOT create a new record for punch_date

        # Always use first punch = check-in, last punch = check-out.
        # Face-recognition ZKTeco devices (like this ZAM70) send all punches
        # with the same or arbitrary status code, so time-order is the only
        # reliable way to determine direction.
        check_in = times[0] if times else None
        check_out = times[-1] if len(times) > 1 else None

        existing = AttendanceRecord.objects.filter(employee=employee, date=punch_date).first()
        flags = compute_attendance_flags(employee, check_in, check_out)
        note = f"ZKTeco ADMS ({len(punch_list)} punch(es))"

        if existing:
            if existing.leave_request_id or existing.status == AttendanceRecord.StatusChoices.PUBLIC_HOLIDAY:
                skipped += 1
                continue
            existing.status = AttendanceRecord.StatusChoices.PRESENT
            existing.check_in = check_in
            if check_out:
                existing.check_out = check_out
            existing.is_late = flags["is_late"]
            existing.is_early_checkout = flags["is_early_checkout"]
            existing.notes = note
            existing.save(update_fields=[
                "status", "check_in", "check_out",
                "is_late", "is_early_checkout", "notes", "updated_at",
            ])
            updated += 1
        else:
            AttendanceRecord.objects.create(
                employee=employee,
                date=punch_date,
                status=AttendanceRecord.StatusChoices.PRESENT,
                check_in=check_in,
                check_out=check_out,
                is_late=flags["is_late"],
                is_early_checkout=flags["is_early_checkout"],
                notes=note,
            )
            created += 1

    logger.info("ADMS sync SN=%s — created=%d updated=%d skipped=%d unknown_ids=%s",
                sn, created, updated, skipped, unknown_ids)

    return HttpResponse(f"OK: {created + updated}", content_type="text/plain")


@csrf_exempt
def iclock_getrequest(request):
    """
    Device polls this endpoint every TransInterval minutes.
    We respond with a DATA QUERY covering the last 2 days so any missed
    punches get re-uploaded.  Full re-syncs are handled by the handshake
    (ATTLOGStamp=0 in _adms_handshake when full_sync_from flag exists).
    """
    sn = request.GET.get("SN", "unknown")
    logger.debug("ADMS getrequest SN=%s", sn)

    from django.utils import timezone as _tz
    from datetime import timedelta

    now = _tz.localtime(_tz.now())
    end = now.strftime("%Y-%m-%d 23:59:59")

    # ZK_FETCH_FROM (settings): force a wide DATA QUERY on EVERY poll. This is the
    # robust one-time historical recovery path — it depends only on deployed code,
    # not on a runtime flag, so there are no file/DB/permission/timing pitfalls.
    # Set ZK_FETCH_FROM = "2026-02-01" in settings, recover, then set back to None.
    fetch_from = getattr(settings, "ZK_FETCH_FROM", None)
    if fetch_from:
        start = f"{fetch_from} 00:00:00"
        cmd = f"C:1:DATA QUERY ATTLOG StartTime={start} EndTime={end}"
        logger.info("ADMS: WIDE-FETCH DATA QUERY to SN=%s (%s -> %s)", sn, start, end)
        return HttpResponse(cmd, content_type="text/plain")

    # Full re-sync requested (reset_and_resync set the DB flag): send ONE wide
    # DATA QUERY covering everything from the requested start date so the device
    # re-uploads historical punches. consume() clears it so the next poll reverts
    # to the normal 2-day window.
    full_sync_date = DeviceSyncFlag.consume()
    if full_sync_date:
        start = f"{full_sync_date.isoformat()} 00:00:00"
        cmd = f"C:1:DATA QUERY ATTLOG StartTime={start} EndTime={end}"
        logger.info("ADMS: FULL-SYNC DATA QUERY to SN=%s (%s → %s)", sn, start, end)
        return HttpResponse(cmd, content_type="text/plain")

    # Normal poll: re-query the last 2 days so any missed punches get re-uploaded.
    start = (now - timedelta(days=2)).strftime("%Y-%m-%d 00:00:00")
    cmd = f"C:1:DATA QUERY ATTLOG StartTime={start} EndTime={end}"
    logger.debug("ADMS: sending DATA QUERY ATTLOG to SN=%s (%s → %s)", sn, start, end)
    return HttpResponse(cmd, content_type="text/plain")


@csrf_exempt
def iclock_devicecmd(request):
    """Device acknowledges a command — always accept."""
    return HttpResponse("OK", content_type="text/plain")


# ════════════════════════════════════════════════════════════════════════════════
# Employee self-punch portal
# ════════════════════════════════════════════════════════════════════════════════

@login_required(login_url="/admin/login/")
def employee_punch_view(request):
    try:
        employee = request.user.employee_profile
    except Exception:
        return render(request, "attendance/punch.html", {
            "error": "Your account is not linked to an employee profile. Contact HR."
        })

    today = timezone.localdate()
    now_time = timezone.localtime().time().replace(second=0, microsecond=0)
    record = AttendanceRecord.objects.filter(employee=employee, date=today).first()
    error_msg = success_msg = None

    if request.method == "POST":
        punch_type = request.POST.get("punch_type")
        from attendance.services import compute_attendance_flags

        if punch_type == "in":
            if record and record.check_in:
                error_msg = "You have already checked in today."
            else:
                record, _ = AttendanceRecord.objects.get_or_create(
                    employee=employee, date=today,
                    defaults={"status": AttendanceRecord.StatusChoices.PRESENT,
                              "notes": "Self punch — portal"},
                )
                record.check_in = now_time
                if record.status not in (AttendanceRecord.StatusChoices.PRESENT,
                                         AttendanceRecord.StatusChoices.HALF_DAY):
                    record.status = AttendanceRecord.StatusChoices.PRESENT
                flags = compute_attendance_flags(employee, record.check_in, None)
                record.is_late = flags["is_late"]
                record.is_early_checkout = False
                record.save()
                return redirect("attendance:employee_punch")

        elif punch_type == "out":
            if not record or not record.check_in:
                error_msg = "Please check in first."
            elif record.check_out:
                error_msg = "You have already checked out today."
            else:
                record.check_out = now_time
                flags = compute_attendance_flags(employee, record.check_in, record.check_out)
                record.is_late = flags["is_late"]
                record.is_early_checkout = flags["is_early_checkout"]
                record.save()
                return redirect("attendance:employee_punch")

    sched_in = employee.scheduled_checkin
    sched_out = employee.scheduled_checkout

    context = {
        "employee": employee,
        "today": today,
        "today_str": today.strftime("%A, %d %b %Y"),
        "record": record,
        "check_in": record.check_in if record else None,
        "check_out": record.check_out if record else None,
        "is_late": record.is_late if record else False,
        "is_early_checkout": record.is_early_checkout if record else False,
        "sched_in": sched_in.strftime("%H:%M") if sched_in else "",
        "sched_out": sched_out.strftime("%H:%M") if sched_out else "",
        "error_msg": error_msg,
        "success_msg": success_msg,
    }
    return render(request, "attendance/punch.html", context)
