"""Download and load CDR or RDR records for a month, reporting progress for each day.

Run from root directory with:

    python database/pds_bulk_load_month.py YYYY MM cdr
    python database/pds_bulk_load_month.py YYYY MM rdr
    python database/pds_bulk_load_month.py YYYY MM cdr --rerun

The daily loader writes products under ``messenger_archive/xrs``. Use --rerun
to reload files already on disk without downloading them again.
"""
from __future__ import annotations
import argparse
import subprocess
import sys
from calendar import monthrange
from datetime import date
from pathlib import Path


DATABASE_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = DATABASE_DIR.parent

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)

    parser.add_argument("year", type=int, choices=range(2011, 2016), help="Year for the month to load")
    parser.add_argument("month", type=int, choices=range(1, 13), help="Month to load")
    parser.add_argument("record_type", choices=["cdr", "rdr"], help="Type of records to load")
    parser.add_argument("--rerun", action="store_true", help="reload files already on disk without downloading")
    args = parser.parse_args(argv)

    last_day = monthrange(args.year, args.month)[1]
    daylist = tuple(date(args.year, args.month, day) for day in range(1, last_day + 1))

    failures = []
    for day in daylist:
        day_text = day.isoformat()
        print(f"\n===== Uploading {args.record_type.upper()} records for {day_text} =====", flush=True)
        command = [sys.executable, "-m", f"database.load_{args.record_type}_records", day_text]
        if args.rerun:
            command.append("--rerun")
        result = subprocess.run(command, cwd=REPOSITORY_ROOT, check=False)
        if result.returncode:
            failures.append(day_text)
            print(
                f"{day_text}: failed with exit code {result.returncode}",
                file=sys.stderr,
                flush=True,
            )

    if failures:
        print(f"Bulk load failed for: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
