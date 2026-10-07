"""Internal downloader for MESSENGER XRS products from the PDS Geosciences Node.

The downloader selects the extensions needed by the XRS database loader and
verifies files against an MD5 checksum when one is published in the PDS4 XML
label. Downloads are also checked against the archive listing's file size.
A failed checksum deletes the file and is reported as an error. Use
``database.load_cds_records`` to download CDR files and load them into the
database in one operation.
"""
import csv
import os
import sys
from concurrent.futures import ThreadPoolExecutor

from .file_downloader import download, list_dir, local_path, make_session
from .pds4_checksum import verify_file

RDR_DATA = "https://pds-geosciences.wustl.edu/messenger/mess-h-xrs-3-rdr-maps-v1/messxrs_3001/data"
CDR_DATA = "https://pds-geosciences.wustl.edu/messenger/mess-e_v_h-xrs-3-cdr-spectra-v1/messxrs_2001/data/"

# The CDR loader needs data records and their XML labels. RDR products use CSV.
REQUIRED_EXTENSIONS = {
    "cdr": {"dat", "xml"},
    "rdr": {"csv", "xml"},
}

CHUNK = 5000


def in_range(parts, start, end):
    """Compare numeric archive path components with inclusive bounds."""
    n = len(parts)
    s, e = start[:n], end[:n]
    return parts[:len(s)] >= s and parts[:len(e)] <= e


def crawl(session, root, start, end, workers):
    files, errors = [], []
    level = [root]

    with ThreadPoolExecutor(workers) as pool:
        while level:
            next_level = []
            for entries, error in pool.map(lambda u: list_dir(session, u), level):
                if error:
                    errors.append(error)

                for child, is_dir, size in entries:
                    if not is_dir:
                        files.append((child, size))
                        continue

                    relative = child[len(root):].strip("/").split("/")
                    if (
                        relative
                        and all(part.isdigit() for part in relative)
                        and not in_range(tuple(map(int, relative)), start, end)
                    ):
                        continue
                    next_level.append(child)

            print(
                f" listed {len(level)} directories, "
                f"{len(files)} files found so far",
                flush=True,
            )
            level = next_level

    return files, errors


def parse_date(text):
    return tuple(int(part) for part in text.split("-")) if text else ()


def extension(url):
    filename = url.rsplit("/", 1)[-1]
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def download_products(
    data_type: str,
    *,
    out: str | os.PathLike[str] = "xrs_pds",
    start_date: str | None = None,
    end_date: str | None = None,
    workers: int = 4,
    dry_run: bool = False,
) -> int:
    """Download selected CDR or RDR products; return nonzero if any operation failed."""
    if data_type not in REQUIRED_EXTENSIONS:
        raise ValueError(f"unsupported XRS data type: {data_type!r}")
    if workers < 1:
        raise ValueError("workers must be positive")

    if data_type == "rdr":
        data_root = RDR_DATA
        roots = [
            f"{data_root.rstrip('/')}/{directory}/"
            for directory in ("footprints", "maps")
        ]
    else:
        data_root = CDR_DATA
        roots = [data_root]

    start, end = parse_date(start_date), parse_date(end_date)
    session = make_session(
        workers,
        user_agent="messenger-xrs-fetch/1.1",
    )
    problems = 0
    todo = []

    required_extensions = REQUIRED_EXTENSIONS[data_type]

    for root in roots:
        print(f"Crawling {root}")
        files, errors = crawl(session, root, start, end, workers)
        for error in errors:
            print(f"LISTING FAILED: {error}", file=sys.stderr)
        problems += len(errors)

        for url, size in files:
            if extension(url) not in required_extensions:
                continue
            relative, destination = local_path(os.fspath(out), root, url)
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
        ThreadPoolExecutor(workers) as pool,
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
                elif error:
                    print(f"WARNING {relative}: {error}", file=sys.stderr)

            completed = min(start_index + len(batch), len(todo))
            print(f"{completed}/{len(todo)} {counts}", flush=True)

    problems += counts["failed"]
    print(f"Done: {counts}. Output in {os.path.abspath(out)}")
    return 1 if problems else 0
