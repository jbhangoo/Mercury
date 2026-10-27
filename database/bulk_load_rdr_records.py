"""Download and load the listed RDR records for a month, reporting progress for each day.

Run from root directory with:

    python database/bulk_load_rdr_records.py
    python database/bulk_load_rdr_records.py --rerun

The daily loader writes products under ``messenger_archive/xrs``. Add or remove
dates in ``DAYS`` to change the catch-up range. Use --rerun to apply footprint
files already on disk without downloading them again.
"""
from __future__ import annotations
# To download a month, set MONTH and LAST_DAY
import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path


MONTH = 8
LAST_DAY = 31
DAYS = tuple(date(2013, MONTH, day) for day in range(1, LAST_DAY + 1))

DATABASE_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = DATABASE_DIR.parent

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rerun", action="store_true", help="apply files already on disk without downloading")
    args = parser.parse_args(argv)

    failures = []
    for day in DAYS:
        day_text = day.isoformat()
        print(f"\n===== Uploading RDR records for {day_text} =====", flush=True)
        command = [
            sys.executable,
            "-m",
            "database.load_rdr_records",
            day_text,
        ]
        if args.rerun:
            command.append("--rerun")
        result = subprocess.run(
            command,
            cwd=REPOSITORY_ROOT,
            check=False,
        )
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
