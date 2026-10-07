"""MD5 verification using checksums published in PDS4 XML labels."""
import hashlib
import os
import re

import requests


def md5_of(path: str) -> str:
    digest = hashlib.md5()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def md5_from_label_text(text: str, filename: str) -> str | None:
    """Find the MD5 for filename in a PDS4 XML label."""
    escaped = re.escape(filename)
    patterns = [
        rf"(?is)<File\b[^>]*>.*?<file_name>\s*{escaped}\s*</file_name>.*?"
        rf"<md5_checksum>\s*([0-9a-f]{{32}})\s*</md5_checksum>.*?</File>",
        rf"(?is)<file_name>\s*{escaped}\s*</file_name>.*?"
        rf"<md5_checksum>\s*([0-9a-f]{{32}})\s*</md5_checksum>",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).lower()
    return None


def label_checksum(
    session: requests.Session,
    product_url: str,
    product_path: str,
) -> tuple[str | None, str]:
    """Fetch the sibling XML label and return its expected MD5."""
    stem = product_url.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    label_url = product_url.rsplit("/", 1)[0] + "/" + stem + ".xml"
    try:
        response = session.get(label_url, timeout=(10, 60))
        response.raise_for_status()
    except Exception as exc:
        return None, f"could not retrieve XML label {label_url}: {exc}"

    text = response.content.decode("utf-8", errors="replace")
    filename = os.path.basename(product_path)
    expected = md5_from_label_text(text, filename)
    if expected is None:
        return None, ""
    return expected, ""


def verify_file(
    session: requests.Session,
    url: str,
    path: str,
) -> tuple[bool, str]:
    expected, error = label_checksum(session, url, path)
    if error:
        return False, error
    if expected is None:
        return True, "PDS label has no MD5 checksum; download size was verified against the archive listing"

    actual = md5_of(path)
    if actual != expected:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        return False, f"MD5 mismatch: expected {expected}, got {actual}; file deleted"
    return True, ""
