#!/usr/bin/env python3
"""
Standalone ZKTeco attendance export script.
Run this on an office PC that can reach the device at 10.11.0.101.

Install:
    pip install pyzk

Run:
    python zk_export.py
    python zk_export.py --host 10.11.0.101 --output attendance_export.csv
"""
import argparse
import csv
import sys


def main():
    parser = argparse.ArgumentParser(description="Export ZKTeco attendance to CSV")
    parser.add_argument("--host", default="10.11.0.101")
    parser.add_argument("--port", type=int, default=4370)
    parser.add_argument("--password", type=int, default=0)
    parser.add_argument("--output", default="attendance_export.csv")
    args = parser.parse_args()

    try:
        from zk import ZK
    except ImportError:
        print("ERROR: pyzk not installed.")
        print("Run:  pip install pyzk")
        sys.exit(1)

    print(f"Connecting to device at {args.host}:{args.port} ...")
    zk = ZK(
        args.host,
        port=args.port,
        timeout=30,
        password=args.password,
        force_udp=False,
        ommit_ping=True,
    )

    conn = None
    try:
        conn = zk.connect()
        print("Connected. Downloading attendance logs (this may take a minute) ...")

        attendances = conn.get_attendance()
        print(f"Retrieved {len(attendances)} punch record(s).")

        with open(args.output, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["user_id", "timestamp", "status", "punch"])
            for att in attendances:
                writer.writerow([
                    att.user_id,
                    att.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                    getattr(att, "status", 0),
                    getattr(att, "punch", 0),
                ])

        print(f"\nDone! Exported to:  {args.output}")
        print("\nNext steps:")
        print("  1. Copy attendance_export.csv to the server")
        print("  2. On the server, run:")
        print("       python manage.py import_attendance_csv /path/to/attendance_export.csv --dry-run")
        print("       python manage.py import_attendance_csv /path/to/attendance_export.csv")

    except Exception as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)
    finally:
        if conn:
            try:
                conn.disconnect()
            except Exception:
                pass


if __name__ == "__main__":
    main()
