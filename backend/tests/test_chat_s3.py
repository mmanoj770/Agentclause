import pytest

from app.config import settings
from app.storage import s3 as s3_module


class Body:
    def __init__(self, data: bytes):
        self.data = data

    def read(self, n: int) -> bytes:
        return self.data[:n]


class FakeS3:
    def __init__(self, data: bytes):
        self.data = data
        self.calls = []

    def get_object(self, **kwargs):
        self.calls.append(kwargs)
        return {"Body": Body(self.data)}


def test_reads_bytes_for_the_given_key():
    fake = FakeS3(b"hello")
    assert s3_module.get_object_bytes(fake, "orgs/a/documents/b/c.pdf") == b"hello"
    assert fake.calls == [{"Bucket": settings.s3_bucket, "Key": "orgs/a/documents/b/c.pdf"}]


def test_refuses_objects_over_the_upload_limit():
    fake = FakeS3(b"x" * (settings.max_upload_bytes + 5))
    with pytest.raises(ValueError):
        s3_module.get_object_bytes(fake, "k")
