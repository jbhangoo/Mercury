#!/usr/bin/env python3
"""
Load every CDS record file for one day into the xrs table.

    python -m database.load_cds_records 2013-04-11
    python -m database.load_cds_records 2013-04-11 --rerun
    python -m database.load_cds_records 2013-04-11 --dry-run
    python -m database.load_cds_records 2013-04-11 --out C:\\xrs_pds

The day's files are expected at <out>/data/YYYY/MM/DD/xrscdr*.dat, each with its
.xml label beside it. By default, the day's files are downloaded from PDS first.
Use --rerun to load files already on disk without downloading. Each file is
loaded in its own transaction, so a bad file is reported and skipped without
undoing the others. Loading is idempotent: rerunning a day updates its rows in
place. Exit status: 0 all loaded, 1 some file failed, 2 nothing to load / bad
arguments.

Set DATABASE_URL in the environment, the repository .env, or server/.env for
the database connection. Any postgresql:// URL is rewritten to
postgresql+psycopg:// (psycopg 3).
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent

if __package__:
    from .pds2db.xrs_downloader import download_products
else:
    from pds2db.xrs_downloader import download_products


def resolve_dsn() -> str | None:
    from dotenv import load_dotenv

    repository_root = HERE.parent
    load_dotenv(repository_root / ".env")
    load_dotenv(repository_root / "server" / ".env", override=False)
    dsn = os.environ.get("DATABASE_URL")
    return re.sub(r"^postgres(?:ql)?(?:\+\w+)?://", "postgresql+psycopg://", dsn) if dsn else None


def day_files(out: Path, day: date) -> list[Path]:
    folder = out / "data" / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}"
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir()
                  if p.is_file() and p.suffix.lower() == ".dat" and p.name.lower().startswith("xrscdr"))


def download_day(out: Path, day: date) -> int:
    return download_products(
        "cdr",
        out=out,
        start_date=day.isoformat(),
        end_date=day.isoformat(),
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("day", help="UTC day to load, YYYY-MM-DD")
    ap.add_argument("--out", default="xrs_pds", help="folder holding data/YYYY/MM/DD/... (default xrs_pds)")
    ap.add_argument("--rerun", action="store_true", help="load files already on disk without downloading")
    ap.add_argument("--dry-run", action="store_true", help="list files on disk without downloading or loading")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        day = date.fromisoformat(args.day)
    except ValueError:
        ap.error(f"day must be YYYY-MM-DD, got {args.day!r}")
    out = Path(args.out)

    if not args.rerun and not args.dry_run and download_day(out, day) != 0:
        print("Download failed; nothing loaded.", file=sys.stderr)
        return 1

    files = day_files(out, day)
    if not files:
        print(f"No xrscdr*.dat files for {day} under {out / 'data'}"
              + (" (use --rerun only when the files are already on disk)"
                 if args.rerun or args.dry_run else ""), file=sys.stderr)
        return 2
    missing = [f.name for f in files if not f.with_suffix(".xml").is_file()]
    if missing:
        print(f"Missing XML labels for {', '.join(missing)}; the label defines the record layout.", file=sys.stderr)
        return 2

    print(f"{day}: {len(files)} file(s): {', '.join(f.name for f in files)}")
    if args.dry_run:
        return 0

    dsn = resolve_dsn()
    if not dsn:
        ap.error("no database: set DATABASE_URL in the environment")

    from sqlalchemy import create_engine
    if __package__:
        from .pds2db.cdr_loader import CDRLoader
    else:
        from pds2db.cdr_loader import CDRLoader

    engine = create_engine(dsn)
    loader = CDRLoader(engine)
    total, failures = 0, []
    try:
        for path in files:
            try:
                written = loader.load_file(path)
                total += written
                print(f"  {path.name}: {written} records")
            except Exception as exc:               # report and keep going with the day's other files
                failures.append((path.name, exc))
                print(f"  {path.name}: FAILED: {exc}", file=sys.stderr)
    finally:
        engine.dispose()

    print(f"{day}: {total} records loaded from {len(files) - len(failures)} of {len(files)} file(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
