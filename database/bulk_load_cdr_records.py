"""Download and load the listed CDR records for a month, reporting progress for each day.

Run from root directory with:

    python database/bulk_load_cdr_records.py

The daily loader writes products under ``database/xrs_pds``. Add or remove
dates in ``DAYS`` to change the catch-up range.
"""
from __future__ import annotations
# To download a month, set MONTH and LAST_DAY
import subprocess
import sys
from datetime import date
from pathlib import Path


MONTH = 11
LAST_DAY = 30
DAYS = tuple(date(2013, MONTH, day) for day in range(1, LAST_DAY + 1))

DATABASE_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = DATABASE_DIR.parent
OUTPUT_DIR = DATABASE_DIR / "xrs_pds"

def main() -> int:
    failures = []
    for day in DAYS:
        day_text = day.isoformat()
        print(f"\n===== Uploading CDR records for {day_text} =====", flush=True)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "database.load_cdr_records",
                day_text,
                "--out",
                str(OUTPUT_DIR),
            ],
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
