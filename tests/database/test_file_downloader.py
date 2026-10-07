import hashlib

from database.pds2db.file_downloader import download, list_dir
from database.pds2db.pds4_checksum import verify_file


class FakeResponse:
    def __init__(self, *, content=b"", text=""):
        self.content = content or text.encode("utf-8")
        self.text = text

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return exc_type is None and exc_value is None and traceback is None

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        for start in range(0, len(self.content), chunk_size):
            yield self.content[start:start + chunk_size]


class FakeSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self.responses)


def make_label(filename, checksum):
    return (
        "<Product><File_Area_Observational><File>"
        f"<file_name>{filename}</file_name>"
        f"<md5_checksum>{checksum}</md5_checksum>"
        "</File></File_Area_Observational></Product>"
    )


def test_list_dir_extracts_child_and_size():
    response = FakeResponse(
        text=(
            '<table><tr><td>12</td><td><a href="product.csv">'
            "product.csv</a></td></tr></table>"
        )
    )
    entries, error = list_dir(FakeSession([response]), "https://example.test/data/")

    assert error is None
    assert entries == [("https://example.test/data/product.csv", False, 12)]


def test_download_verifies_pds_label_checksum(tmp_path):
    payload = b"XRS data"
    checksum = hashlib.md5(payload).hexdigest()
    session = FakeSession([
        FakeResponse(content=payload),
        FakeResponse(text=make_label("product.csv", checksum)),
    ])
    destination = tmp_path / "product.csv"

    result = download(
        session,
        "https://example.test/data/product.csv",
        len(payload),
        "product.csv",
        str(destination),
        verifier=verify_file,
    )

    assert result == ("product.csv", "downloaded", "")
    assert destination.read_bytes() == payload
    assert not (tmp_path / "product.csv.part").exists()


def test_download_accepts_pds_label_without_checksum_after_size_check(tmp_path):
    payload = b"XRS data"
    session = FakeSession([
        FakeResponse(content=payload),
        FakeResponse(text="<Product><File><file_name>product.dat</file_name></File></Product>"),
    ])
    destination = tmp_path / "product.dat"

    result = download(
        session,
        "https://example.test/data/product.dat",
        len(payload),
        "product.dat",
        str(destination),
        verifier=verify_file,
    )

    assert result == (
        "product.dat",
        "downloaded",
        "PDS label has no MD5 checksum; download size was verified against the archive listing",
    )
    assert destination.read_bytes() == payload


def test_download_removes_file_when_checksum_does_not_match(tmp_path):
    payload = b"bad data"
    session = FakeSession([
        FakeResponse(content=payload),
        FakeResponse(text=make_label("product.csv", "0" * 32)),
    ])
    destination = tmp_path / "product.csv"

    result = download(
        session,
        "https://example.test/data/product.csv",
        len(payload),
        "product.csv",
        str(destination),
        verifier=verify_file,
    )

    assert result[0:2] == ("product.csv", "failed")
    assert "MD5 mismatch" in result[2]
    assert not destination.exists()
    assert not (tmp_path / "product.csv.part").exists()


def test_download_removes_partial_file_after_size_mismatch(tmp_path):
    session = FakeSession([FakeResponse(content=b"short")])
    destination = tmp_path / "nested" / "product.csv"

    result = download(
        session,
        "https://example.test/data/product.csv",
        100,
        "product.csv",
        str(destination),
    )

    assert result[0:2] == ("product.csv", "failed")
    assert "size mismatch" in result[2]
    assert not destination.exists()
    assert not (destination.parent / "product.csv.part").exists()
