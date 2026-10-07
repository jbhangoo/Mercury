"""Reusable HTTP directory-listing and file-transfer helpers."""
import os
import re
from collections.abc import Callable
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def make_session(
    workers: int,
    user_agent: str = "mercury-file-downloader/1.1",
) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=1.0,
        allowed_methods=("GET",),
        status_forcelist=(429, 500, 502, 503, 504),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=workers,
        pool_maxsize=workers,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers["User-Agent"] = user_agent
    return session


class ListingParser(HTMLParser):
    """Parse an IIS-style directory listing."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: list[tuple[str, str]] = []
        self._text = ""
        self._before = ""
        self._href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._before, self._text = self._text, ""

    def handle_data(self, data: str) -> None:
        if self._href is None:
            self._text += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            self.entries.append((self._href, self._before))
            self._href = None


def list_dir(
    session: requests.Session,
    url: str,
) -> tuple[list[tuple[str, bool, int | None]], str | None]:
    """Return child URLs, directory flags, optional sizes, and an error."""
    try:
        response = session.get(url, timeout=(10, 60))
        response.raise_for_status()
    except Exception as exc:
        return [], f"{url}: {exc}"

    parser = ListingParser()
    parser.feed(response.text)
    output = []

    for href, before in parser.entries:
        child = urljoin(url, href)
        if not child.startswith(url) or child == url:
            continue

        match = re.search(r"(\d+|)$", before.rstrip())
        token = match.group(1) if match else None
        is_dir = token == "" or child.endswith("/")
        if is_dir and not child.endswith("/"):
            child += "/"
        size = int(token) if token and token.isdigit() and not is_dir else None
        output.append((child, is_dir, size))

    return output, None


def local_path(out_root: str, root: str, url: str) -> tuple[str, str]:
    """Map a URL beneath an archive root to its relative and local paths."""
    base = root.rstrip("/").rsplit("/", 1)[0] + "/"
    relative = unquote(url[len(base):])
    return relative, os.path.join(out_root, *relative.split("/"))


def download(
    session: requests.Session,
    url: str,
    size: int | None,
    relative: str,
    destination: str,
    verifier: Callable[[requests.Session, str, str], tuple[bool, str]] | None = None,
) -> tuple[str, str, str]:
    """Download one file, optionally validating it before reporting success."""
    if (
        os.path.exists(destination)
        and os.path.getsize(destination) > 0
        and (size is None or os.path.getsize(destination) == size)
    ):
        return relative, "skipped", ""

    os.makedirs(os.path.dirname(destination), exist_ok=True)
    temporary = destination + ".part"
    installed = False

    try:
        received = 0
        verification_message = ""
        with session.get(url, stream=True, timeout=(10, 120)) as response:
            response.raise_for_status()
            with open(temporary, "wb") as handle:
                for chunk in response.iter_content(65536):
                    if chunk:
                        handle.write(chunk)
                        received += len(chunk)

        if size is not None and received != size:
            raise IOError(f"size mismatch: got {received} bytes, listing says {size}")

        os.replace(temporary, destination)
        installed = True
        if verifier is not None:
            verified, verification_message = verifier(session, url, destination)
            if not verified:
                raise IOError(verification_message)
        return relative, "downloaded", verification_message

    except Exception as exc:
        if os.path.exists(temporary):
            os.remove(temporary)
        if installed and os.path.exists(destination):
            os.remove(destination)
        return relative, "failed", str(exc)
