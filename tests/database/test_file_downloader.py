import hashlib

from database.pds2db.file_downloader import download
from database.pds2db.pds4_checksum import verify_file


class FakeResponse:
    def __init__(self, content):
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        for start in range(0, len(self.content), chunk_size):
            yield self.content[start:start + chunk_size]


class FakeSession:
    def __init__(self, responses):
        self.responses = responses

    def get(self, url, **kwargs):
        return self.responses[url]


def test_download_with_checksum_verifier(tmp_path):
    url = "https://example.test/product.dat"
    payload = b"product data"
    checksum = hashlib.md5(payload).hexdigest()
    session = FakeSession({
        url: FakeResponse(payload),
        "https://example.test/product.xml": FakeResponse(
            f"<File><file_name>product.dat</file_name><md5_checksum>{checksum}</md5_checksum></File>"
            .encode()
        ),
    })
    destination = tmp_path / "product.dat"

    result = download(session, url, len(payload), "product.dat", str(destination), verifier=verify_file)

    assert result == ("product.dat", "downloaded", "")
    assert destination.is_file()
    assert destination.read_bytes() == payload


def test_download_without_verifier(tmp_path):
    url = "https://example.test/product.dat"
    payload = b"product data"
    session = FakeSession({url: FakeResponse(payload)})
    destination = tmp_path / "product.dat"

    result = download(session, url, len(payload), "product.dat", str(destination))

    assert result == ("product.dat", "downloaded", "")
    assert destination.is_file()
    assert destination.read_bytes() == payload
