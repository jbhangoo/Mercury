"""MD5 verification using checksums published in PDS4 XML labels."""
import hashlib
import os
import xml.etree.ElementTree as ET
import requests


def md5_calculated(path: str) -> str:
    """Calculate the MD5 checksum of a local file in chunks."""
    hasher = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1_048_576), b""):  # 1MB blocks
            hasher.update(chunk)
    return hasher.hexdigest()


def md5_fromfile(label_text: str, filename: str) -> str | None:
    """Extract expected MD5 checksum for a file from PDS4 XML using ElementTree."""
    try:
        root = ET.fromstring(label_text)
        # Use wildcard namespace lookup to avoid hardcoding PDS4 version namespaces
        for file_elem in root.findall(".//{*}File"):
            name_elem = file_elem.find("{*}file_name")
            if name_elem is not None and name_elem.text and name_elem.text.strip() == filename:
                checksum_elem = file_elem.find("{*}md5_checksum")
                if checksum_elem is not None and checksum_elem.text:
                    return checksum_elem.text.strip().lower()
    except ET.ParseError:
        pass
    return None


def verify_file(
    session: requests.Session,
    data_url: str,
    path: str,
) -> tuple[bool, str]:
    """Fetch the sibling XML label, extract its MD5, and compare it against the downloaded file."""
    # Derive XML label URL from the data file URL
    base_url = data_url.rsplit("/", 1)[0]
    stem = data_url.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    label_url = f"{base_url}/{stem}.xml"

    try:
        response = session.get(label_url, timeout=(10, 60))
        response.raise_for_status()
    except Exception as exc:
        return False, f"could not retrieve XML label {label_url}: {exc}"

    expected = md5_fromfile(response.text, os.path.basename(path))
    if not expected:
        return True, "PDS label has no MD5 checksum"

    actual = md5_calculated(path)
    if actual == expected:
        return True, ""

    # MD5 mismatch: delete the file to avoid leaving a corrupted file on disk
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    return False, f"MD5 mismatch: expected {expected}, got {actual}; file deleted"
        