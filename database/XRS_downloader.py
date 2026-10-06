#!/usr/bin/env python3
"""
Download MESSENGER XRS products from the PDS Geosciences Node by walking the
archive's directory listings.

Why a crawler: the collection inventories list products by ID
(e.g. xrs_fp_1_209415518_csv), but footprints live in date folders
(footprints/YYYY/MM/DD/HH/xrs_fp_1_209415518.csv) that cannot be derived
from the ID, so paths have to be discovered from the listings.

Reproducible and resumable: files whose size already matches the listing are
skipped, downloads are written to *.part and renamed only when complete, and a
manifest.csv records every file considered. Exit status is non-zero if any
directory listing or download failed.

Examples
  python XRS_Loader.py --data-type cdr --dry-run
  python XRS_Loader.py --data-type rdr --start 2013-04 --end 2013-04 --out xrs_pds
  python XRS_Loader.py --data-type cdr --verify
Keep --out short on Windows (260-character path limit).
"""
import argparse
import csv
import hashlib
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

RDR_DATA = "https://pds-geosciences.wustl.edu/messenger/mess-h-xrs-3-rdr-maps-v1/messxrs_3001/data"
CDR_DATA = "https://pds-geosciences.wustl.edu/messenger/mess-e_v_h-xrs-3-cdr-spectra-v1/messxrs_2001/data/"

CHUNK = 5000  # files submitted to the pool at a time (bounds memory)


def make_session(workers: int) -> requests.Session:
    session = requests.Session()
    retry = Retry(total=5, backoff_factor=1.0, allowed_methods=("GET",),
                  status_forcelist=(429, 500, 502, 503, 504))
    adapter = HTTPAdapter(max_retries=retry, pool_connections=workers, pool_maxsize=workers)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers["User-Agent"] = "mercury-xrs-fetch/1.0"
    return session


class ListingParser(HTMLParser):
    """Parses an IIS-style listing: '<date> <time> <size|<dir>> <A HREF=..>name</A>'."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: list[tuple[str, str]] = []  # (href, text before the link)
        self._text = ""
        self._before = ""
        self._href = None

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._before, self._text = self._text, ""

    def handle_data(self, data):
        if self._href is None:
            self._text += data

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.entries.append((self._href, self._before))
            self._href = None


def list_dir(session, url):
    """Returns ([(child_url, is_dir, size_or_None)], error_or_None)."""
    try:
        resp = session.get(url, timeout=(10, 60))
        resp.raise_for_status()
    except Exception as exc:
        return [], f"{url}: {exc}"
    parser = ListingParser()
    parser.feed(resp.text)
    out = []
    for href, before in parser.entries:
        child = urljoin(url, href)
        if not child.startswith(url) or child == url:  # parent link, external links
            continue
        match = re.search(r"(\d+|<dir>)$", before.rstrip())
        token = match.group(1) if match else None
        is_dir = token == "<dir>" or child.endswith("/")
        if is_dir and not child.endswith("/"):
            child += "/"
        size = int(token) if token and token.isdigit() and not is_dir else None
        out.append((child, is_dir, size))
    return out, None


def in_range(parts, start, end):
    """parts, start, end are tuples like (2013, 4, 11); start/end may be shorter."""
    n = len(parts)
    s, e = start[:n], end[:n]
    return parts[:len(s)] >= s and parts[:len(e)] <= e


def crawl(session, root, start, end, workers):
    files, errors = [], []
    level = [root]
    with ThreadPoolExecutor(workers) as pool:
        while level:
            nxt = []
            for entries, error in pool.map(lambda u: list_dir(session, u), level):
                if error:
                    errors.append(error)
                for child, is_dir, size in entries:
                    if not is_dir:
                        files.append((child, size))
                        continue
                    rel = child[len(root):].strip("/").split("/")
                    if all(p.isdigit() for p in rel) and not in_range(tuple(map(int, rel)), start, end):
                        continue  # outside the requested date range
                    nxt.append(child)
            print(f"  listed {len(level)} directories, {len(files)} files found so far", flush=True)
            level = nxt
    return files, errors


def local_path(out_root, root, url):
    base = root.rstrip("/").rsplit("/", 1)[0] + "/"   # keep 'footprints/...' / 'maps/...'
    rel = unquote(url[len(base):])
    return rel, os.path.join(out_root, *rel.split("/"))


def download(session, url, size, rel, dest):
    if os.path.exists(dest) and os.path.getsize(dest) > 0 and (size is None or os.path.getsize(dest) == size):
        return rel, "skipped", ""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    try:
        got = 0
        with session.get(url, stream=True, timeout=(10, 60)) as resp:
            resp.raise_for_status()
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_content(65536):
                    fh.write(chunk)
                    got += len(chunk)
        if size is not None and got != size:
            raise IOError(f"size mismatch: got {got} bytes, listing says {size}")
        os.replace(tmp, dest)
        return rel, "downloaded", ""
    except Exception as exc:
        if os.path.exists(tmp):
            os.remove(tmp)
        return rel, "failed", str(exc)


def md5_of(path):
    digest = hashlib.md5()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_labels(out_root):
    """Checks data files against md5_checksum values in their PDS4 .xml labels.
    Only files whose label actually carries an md5 are checked."""
    checked, bad = 0, []
    for dirpath, _, names in os.walk(out_root):
        for name in names:
            if not name.endswith(".xml"):
                continue
            with open(os.path.join(dirpath, name), encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            for block in re.findall(r"<File>.*?</File>", text, re.S):
                fname = re.search(r"<file_name>\s*(.*?)\s*</file_name>", block, re.S)
                md5 = re.search(r"<md5_checksum>\s*([0-9a-fA-F]{32})\s*</md5_checksum>", block)
                target = os.path.join(dirpath, fname.group(1)) if fname else None
                if md5 and target and os.path.exists(target):
                    checked += 1
                    if md5_of(target) != md5.group(1).lower():
                        bad.append(target)
    return checked, bad


def parse_date(text):
    return tuple(int(p) for p in text.split("-")) if text else ()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-type", choices=("cdr", "rdr"), required=True,
                    help="PDS data collection to crawl: cdr or rdr")
    ap.add_argument("--out", default="xrs_pds", help="output directory (default: xrs_pds)")
    ap.add_argument("--start", help="first date to include: YYYY[-MM[-DD[-HH]]]")
    ap.add_argument("--end", help="last date to include: YYYY[-MM[-DD[-HH]]]")
    ap.add_argument("--workers", type=int, default=4, help="parallel connections (default 4; be polite)")
    ap.add_argument("--skip-ext", nargs="*", default=["lbl"], help="extensions to skip (default: lbl, the PDS3 labels)")
    ap.add_argument("--ext", nargs="*", help="only download these extensions (default: everything not skipped)")
    ap.add_argument("--dry-run", action="store_true", help="list what would be downloaded, then stop")
    ap.add_argument("--verify", action="store_true", help="after downloading, check md5s from the XML labels")
    args = ap.parse_args()

    if args.data_type == "rdr":
        data_root = RDR_DATA
        roots = [f"{data_root.rstrip('/')}/{directory}/" for directory in ("footprints", "maps")]
    else:
        data_root = CDR_DATA
        roots = [data_root]
    start, end = parse_date(args.start), parse_date(args.end)
    skip = {e.lower().lstrip(".") for e in args.skip_ext}
    only = {e.lower().lstrip(".") for e in args.ext} if args.ext else None
    session = make_session(args.workers)

    problems = 0
    todo = []
    for root in roots:
        print(f"Crawling {root}")
        files, errors = crawl(session, root, start, end, args.workers)
        for err in errors:
            print(f"  LISTING FAILED: {err}", file=sys.stderr)
        problems += len(errors)
        for url, size in files:
            ext = url.rsplit(".", 1)[-1].lower() if "." in url.rsplit("/", 1)[-1] else ""
            if ext in skip or (only is not None and ext not in only):
                continue
            rel, dest = local_path(args.out, root, url)
            todo.append((url, size, rel, dest))

    print(f"{len(todo)} files selected")
    if args.dry_run:
        by_ext: dict[str, list[int]] = {}
        for url, size, _, _ in todo:
            ext = url.rsplit(".", 1)[-1].lower()
            entry = by_ext.setdefault(ext, [0, 0, 0])
            entry[0] += 1
            entry[1] += size or 0
            entry[2] += size is None
        for ext, (n, nbytes, unknown) in sorted(by_ext.items()):
            note = f" ({unknown} with unknown size)" if unknown else ""
            print(f"  .{ext}: {n} files, {nbytes / 1e9:.3f} GB{note}")
        print(f"  total: {sum(e[1] for e in by_ext.values()) / 1e9:.3f} GB (sum of sizes in the listings; "
              "on-disk use is higher because of cluster rounding)")
        for url, size, rel, _ in todo[:20]:
            print(f"  {rel}  ({size} bytes)")
        if len(todo) > 20:
            print(f"  ... and {len(todo) - 20} more")
        return 1 if problems else 0

    os.makedirs(args.out, exist_ok=True)
    counts = {"downloaded": 0, "skipped": 0, "failed": 0}
    with open(os.path.join(args.out, "manifest.csv"), "w", newline="", encoding="utf-8") as mf, \
            ThreadPoolExecutor(args.workers) as pool:
        writer = csv.writer(mf)
        writer.writerow(["path", "status", "error"])
        done = 0
        for i in range(0, len(todo), CHUNK):
            batch = todo[i:i + CHUNK]
            for rel, status, error in pool.map(lambda t: download(session, *t), batch):
                counts[status] += 1
                writer.writerow([rel, status, error])
                if status == "failed":
                    print(f"  FAILED {rel}: {error}", file=sys.stderr)
            done += len(batch)
            print(f"  {done}/{len(todo)}  {counts}", flush=True)
    problems += counts["failed"]

    if args.verify:
        checked, bad = verify_labels(args.out)
        print(f"MD5 verified {checked} files against their labels; {len(bad)} mismatches")
        for path in bad:
            print(f"  MD5 MISMATCH {path}", file=sys.stderr)
        problems += len(bad)

    print(f"Done: {counts}. Output in {os.path.abspath(args.out)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())