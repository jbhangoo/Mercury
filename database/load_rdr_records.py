#!/usr/bin/env python3
"""
Download RDR footprint files for one day and apply them to the xrs table.

Each footprint belongs to a CDR row that must already be loaded (run load_cdr_records
for the day first). A footprint is reduced to the radius of the circle around the row's
boresight point that lies inside it, which is stored with the clock partition; the
footprint itself is not kept. Footprints that cannot be applied (no CDR row, no boresight
point, boresight point not inside the footprint) are counted and reported, and the exit
status is 1 only if a file fails or nothing at all could be applied. A footprint that is
already applied is skipped unless --force is given.

    python -m database.load_rdr_records 2013-04-11
    python -m database.load_rdr_records 2013-04-11 --rerun
    python -m database.load_rdr_records 2013-04-11 --rerun --force
    python -m database.load_rdr_records 2013-04-11 --dry-run
    python -m database.load_rdr_records 2013-04-11 --download-only

Use --download-only to download the day's products and verify that footprint CSVs
and their XML labels are discoverable, without parsing records or connecting to
the database. --dry-run only checks files already on disk and does not download.
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from statistics import median

HERE = Path(__file__).resolve().parent

if __package__:
    from .database_consts import XRS_ARCHIVE_DIR
    from .pds2db.pds_downloader import download_products
    from .pds2db.pds_consts import (
        FOOTPRINT_APPLIED,
        FOOTPRINT_MATCHED_BY_TIME,
        FOOTPRINT_PROBLEM,
        FOOTPRINT_UNCHANGED,
        FOOTPRINT_UPDATED,
    )
else:
    from database.database_consts import XRS_ARCHIVE_DIR
    from database.pds2db.pds_downloader import download_products
    from database.pds2db.pds_consts import (
        FOOTPRINT_APPLIED,
        FOOTPRINT_MATCHED_BY_TIME,
        FOOTPRINT_PROBLEM,
        FOOTPRINT_UNCHANGED,
        FOOTPRINT_UPDATED,
    )


def resolve_dsn() -> str | None:
    from dotenv import load_dotenv

    repository_root = HERE.parent
    load_dotenv(repository_root / ".env")
    load_dotenv(repository_root / "server" / ".env", override=False)
    dsn = os.environ.get("DATABASE_URL")
    return re.sub(r"^postgres(?:ql)?(?:\+\w+)?://", "postgresql+psycopg://", dsn) if dsn else None


def find_xml_label(csv_path: Path) -> Path | None:
    """Finds the corresponding XML label regardless of casing (.xml vs .XML)."""
    for ext in [".xml", ".XML"]:
        candidate = csv_path.with_suffix(ext)
        if candidate.is_file():
            return candidate
    return None


def day_files(out: Path, day: date) -> list[Path]:
    """
    Finds all xrs_fp_*.csv footprint files for a given date across all subdirectories.
    Handles YYYY/MM/DD/HH, YYYY/M/D/H, or flat date folder structures.
    """
    # Start looking from <out>/footprints if it exists, otherwise fallback to <out>

    if not out.is_dir():
        print(f"Error: {out} is not a directory.", file=sys.stderr)
        return []
    elif (out / "footprints").is_dir():
        search_base = out / "footprints"
    else:
        search_base = out

    # Format variations to catch zero-padded and non-zero-padded paths
    date_patterns = [
        f"{day:%Y}/{day:%m}/{day:%d}",  # YYYY/MM/DD
        f"{day.year}/{day.month}/{day.day}"  # YYYY/M/D
    ]

    csv_files = []
    
    # Find all CSV files matching xrs_fp_*.csv
    filepath = search_base.rglob("xrs_fp_*.csv")
    for csv_path in filepath:
        # Convert path to posix format for uniform slash matching
        posix_path = csv_path.as_posix()
        
        # Ensure the file path contains the target date structure
        if any(pattern in posix_path for pattern in date_patterns):
            csv_files.append(csv_path)

    return sorted(csv_files)

def download_day(out: Path, day: date) -> int:
    return download_products(
        "rdr",
        out=out,
        start_date=day.isoformat(),
        end_date=day.isoformat(),
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("day", help="UTC day to load, YYYY-MM-DD")
    ap.add_argument("--rerun", action="store_true", help="update based on files already on disk without downloading")
    ap.add_argument("--force", action="store_true", help="rewrite footprints that are already applied")
    ap.add_argument(
        "--match-by-time",
        action="store_true",
        help="when no CDR row has a footprint's MET, match the row that starts at the footprint's start time",
    )
    ap.add_argument("--dry-run", action="store_true", help="list files on disk without downloading anything or updating database")
    ap.add_argument(
        "--download-only",
        action="store_true",
        help="download and verify footprint files without parsing them or updating the database",
    )
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.download_only and (args.rerun or args.dry_run):
        ap.error("--download-only cannot be combined with --rerun or --dry-run")

    try:
        day = date.fromisoformat(args.day)
    except ValueError:
        ap.error(f"day must be YYYY-MM-DD, got {args.day!r}")
        
    out = XRS_ARCHIVE_DIR

    if not args.rerun and not args.dry_run and download_day(out, day) != 0:
        print(f"{day}: failed (nothing downloaded and no records updated).", file=sys.stderr)
        return 1

    csv_files = day_files(out, day)
    if not csv_files:
        print(f"No xrs_fp_*.csv files for {day} under {out / 'footprints'}"
              + (" (use --rerun only when the files are already on disk)"
                 if args.rerun or args.dry_run else ""), file=sys.stderr)
        return 2

    # Verify matching XML labels exist for every CSV
    missing = [f.name for f in csv_files if find_xml_label(f) is None]
    if missing:
        print(f"Missing XML labels for {', '.join(missing)}; the label defines the record layout.", file=sys.stderr)
        return 2

    print(f"{day}: Found {len(csv_files)} CSV file(s) on disk")
    if args.dry_run or args.download_only:
        return 0

    dsn = resolve_dsn()
    if not dsn:
        ap.error("no database: set DATABASE_URL in the environment")

    from sqlalchemy import create_engine
    if __package__:
        from .pds2db.rdr_updater import RDRUpdater
    else:
        from pds2db.rdr_updater import RDRUpdater

    engine = create_engine(dsn)
    updater = RDRUpdater(engine, match_by_time=args.match_by_time)
    results, failures = [], []
    try:
        for path in csv_files:
            try:
                results.append(updater.update_from_file(path, force=args.force))
            except Exception as exc:
                failures.append((path.name, exc))
                print(f"  {path.name}: FAILED: {exc}", file=sys.stderr)
        expected, missing = missing_footprints(engine, day, results)
    finally:
        engine.dispose()

    status = report(day, len(csv_files), results, failures)
    report_missing(day, expected, missing)
    return status


def missing_footprints(engine, day: date, results: list):
    """(rows that should have a footprint, those no footprint file reached) for a UTC day.

    A CDR row should have one when its FOV status is 1 or 3 (the SIS); other rows have none. A row
    counts as reached if any footprint file was matched to it, even one that could not be applied
    (that shows up in the report as not applied). Rows within seconds of midnight can have their
    footprint filed under the neighboring day, so a miss at either end of the day may not be real."""
    from server.app.db.access import db_xrs_rows_expecting_footprints
    start = datetime.combine(day, time(0), tzinfo=timezone.utc)
    with engine.connect() as connection:
        expected = db_xrs_rows_expecting_footprints(connection, start, start + timedelta(days=1))
    reached = {r.row_id for r in results if getattr(r, "row_id", None) is not None}
    return expected, [row for row in expected if row["id"] not in reached]


def report_missing(day: date, expected: list, missing: list) -> None:
    if not missing:
        print(f"{day}: all {len(expected)} CDR row(s) with FOV status 1 or 3 were reached by a footprint file")
        return
    shown = ", ".join(f"MET {row['met']}" for row in missing[:5]) + (f" and {len(missing) - 5} more" if len(missing) > 5 else "")
    print(f"{day}: {len(missing)} of {len(expected)} CDR row(s) with FOV status 1 or 3 have no footprint file "
          f"({shown})", file=sys.stderr)


def report(day: date, file_count: int, results: list, failures: list) -> int:
    """Prints what happened to the day's footprints; returns the exit status."""
    problems = [r for r in results if r.status & FOOTPRINT_PROBLEM]
    problem_bits = [
        1 << bit for bit in range(FOOTPRINT_PROBLEM.bit_length())
        if FOOTPRINT_PROBLEM & (1 << bit)
    ]
    for result in problems[:5]:
        print(f"  {result.source_file}: not applied: {result.summary}", file=sys.stderr)
    if len(problems) > 5:
        print(f"  ... and {len(problems) - 5} more not applied", file=sys.stderr)

    updated = sum(bool(r.status & FOOTPRINT_UPDATED) for r in results)
    unchanged = sum(bool(r.status & FOOTPRINT_UNCHANGED) for r in results)
    print(f"{day}: {updated} updated, {unchanged} unchanged (already loaded), "
          f"{len(problems)} not applied, {len(failures)} failed, of {file_count} footprint file(s)")
    if problems:
        print("  not applied: " + ", ".join(
            f"{sum(bool(r.status & bit) for r in problems)} status 0x{bit:02x}"
            for bit in problem_bits
            if any(r.status & bit for r in problems)
        ))
    by_time = [r for r in results if r.status & FOOTPRINT_MATCHED_BY_TIME]
    if by_time:
        met_offsets = sorted({r.met_offset for r in by_time})
        relation = (f"always {met_offsets[0]:+d}" if len(met_offsets) == 1 else
                    f"{len(met_offsets)} different values, from {met_offsets[0]:+d} to {met_offsets[-1]:+d}")
        print(f"  {len(by_time)} matched by start time because no CDR row had the footprint's MET; "
              f"CDR MET minus footprint MET: {relation}")
    offsets = [abs(r.offset_seconds) for r in results if r.offset_seconds is not None]
    if offsets:
        print(f"  CDR start time vs footprint label start: median {median(offsets):.1f} s, "
              f"largest {max(offsets):.1f} s")
    if results and not any(r.status & FOOTPRINT_APPLIED for r in results):
        print(f"{day}: no footprint could be applied; is the CDR file for this day loaded?", file=sys.stderr)
        return 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())