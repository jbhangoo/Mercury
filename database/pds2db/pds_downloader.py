"""
Internal downloader for MESSENGER XRS products from the PDS Geosciences Node.
"""
import csv
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from urllib.parse import unquote, urlsplit

from ..database_consts import XRS_ARCHIVE_DIR
from .file_downloader import download, list_dir, make_session
from .pds4_checksum import verify_file

RDR_DATA = "https://pds-geosciences.wustl.edu/messenger/mess-h-xrs-3-rdr-maps-v1/messxrs_3001/data/footprints/"
CDR_DATA = "https://pds-geosciences.wustl.edu/messenger/mess-e_v_h-xrs-3-cdr-spectra-v1/messxrs_2001/data/"
RDR_EXTS = {"csv", "xml"}
CDR_EXTS = {"dat", "xml"}


CHUNK = 5000
WORKERS = 4


def crawl(session, root: str, target_date: date):
    """List files beneath one PDS day directory, including any nested hour directories."""
    files, errors = [], []
    day_root = f"{root.rstrip('/')}/{target_date:%Y/%m/%d}/"
    level = [day_root]

    with ThreadPoolExecutor(WORKERS) as pool:
        while level:
            next_level = []
            for entries, error in pool.map(lambda u: list_dir(session, u), level):
                if error:
                    errors.append(error)

                for child, is_dir, size in entries:
                    if not is_dir:
                        files.append((child, size))
                        continue

                    next_level.append(child)

            level = next_level

    return files, errors


def extension(url):
    """Return the file extension of a URL, or an empty string if none."""
    filename = url.rsplit("/", 1)[-1]
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _download_files(
    target_date: date,
    source: str,
    required_extensions: set[str],
    dry_run: bool = False,
) -> int:
    """Common core function handling crawling, filtering, downloading, and logging."""

    session = make_session(WORKERS, user_agent="messenger-xrs-fetch/1.1")

    problems = 0
    todo = []
    out = XRS_ARCHIVE_DIR

    print(f"Crawling {source}")
    files, errors = crawl(session, source, target_date)
    for error in errors:
        print(f"LISTING FAILED: {error}", file=sys.stderr)
    problems += len(errors)

    for url, size in files:
        if extension(url) not in required_extensions:
            continue
        path = unquote(urlsplit(url).path)
        if source == RDR_DATA:
            relative = f"footprints/{path.split('/footprints/', 1)[1]}"
        else:
            relative = f"data/{path.split('/data/', 1)[1]}"
        destination = os.path.join(out, *relative.split("/"))
        todo.append((url, size, relative, destination))

    print(
        f"{len(todo)} files selected "
        f"(extensions: {', '.join(sorted(required_extensions))})"
    )

    if dry_run:
        for url, size, relative, _ in todo[:20]:
            print(f"{relative} ({size if size is not None else 'unknown'} bytes)")
        if len(todo) > 20:
            print(f"... and {len(todo) - 20} more")
        return 1 if problems else 0

    os.makedirs(out, exist_ok=True)
    counts = {"downloaded": 0, "skipped": 0, "failed": 0}

    with (
        open(os.path.join(out, "manifest.csv"), "w", newline="", encoding="utf-8") as manifest,
        ThreadPoolExecutor(WORKERS) as pool,
    ):
        writer = csv.writer(manifest)
        writer.writerow(["path", "status", "error"])

        for start_index in range(0, len(todo), CHUNK):
            batch = todo[start_index:start_index + CHUNK]
            for relative, status, error in pool.map(
                lambda item: download(
                    session,
                    *item,
                    verifier=verify_file if extension(item[0]) != "xml" else None,
                ),
                batch,
            ):
                counts[status] += 1
                writer.writerow([relative, status, error])
                if status == "failed":
                    print(f"FAILED {relative}: {error}", file=sys.stderr)
                elif status == "skipped":
                    print(f"SKIPPED {relative}: already on disk")
                elif error:
                    print(f"WARNING {relative}: {error}", file=sys.stderr)

            completed = min(start_index + len(batch), len(todo))
            print(f"{completed}/{len(todo)} files processed", flush=True)

    problems += counts["failed"]
    print(f"Wrote {counts['downloaded']} file(s) to {os.path.abspath(out)}")
    if counts["skipped"]:
        print(f"   {counts['skipped']} file(s) already on disk -- skipped")
    if counts["failed"]:
        print(f"   {counts['failed']} file(s) failed!", file=sys.stderr)
    return 1 if problems else 0


def download_cdr_day(
    target_date: date,
    dry_run: bool = False,
) -> int:
    """Download CDR data files and XML labels for a specific date."""
    return _download_files(
        target_date=target_date,
        source=CDR_DATA,
        required_extensions=CDR_EXTS,
        dry_run=dry_run,
    )


def download_rdr_day(
    target_date: date,
    dry_run: bool = False,
) -> int:
    """Download RDR footprint CSV files and XML labels for a specific date."""
    return _download_files(
        target_date=target_date,
        source=RDR_DATA,
        required_extensions=RDR_EXTS,
        dry_run=dry_run,
    )