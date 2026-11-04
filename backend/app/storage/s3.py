"""S3 presigned upload and download URLs.

Authorisation is the caller's job: check the role and document visibility BEFORE using
these helpers. A download key must come from the database, never from request input.
No credentials ever leave this module: only URLs and signed form fields.
"""
import os
import re
import uuid
from functools import lru_cache

import boto3
from botocore.config import Config
from fastapi import HTTPException

from app.config import settings

# Content type -> the extension the stored file gets (the client's extension is not trusted).
EXTENSIONS = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "image/png": "png",
    "image/jpeg": "jpg",
}

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_UUID_PREFIX = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}-")


@lru_cache(maxsize=1)
def _client():
    kwargs = {}
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs.update(
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            aws_session_token=settings.aws_session_token,
        )
    return boto3.client(
        "s3",
        region_name=settings.aws_region,
        endpoint_url=settings.s3_endpoint_url or f"https://s3.{settings.aws_region}.amazonaws.com",
        config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
        **kwargs,
    )


def get_s3():
    """FastAPI dependency. Tests override it with a client that never reaches AWS."""
    if not settings.s3_bucket:
        raise HTTPException(503, "File storage is not configured")
    return _client()


def safe_stem(filename: str) -> str:
    # Both separators: a Windows path posted from a browser must not leak its folders.
    stem = os.path.splitext(filename.replace("\\", "/").rsplit("/", 1)[-1])[0]
    return _UNSAFE.sub("_", stem)[:80].strip("._") or "file"


def key_prefix(org_id, doc_id) -> str:
    return f"orgs/{org_id}/documents/{doc_id}/"


def object_key(org_id, doc_id, filename: str, content_type: str) -> str:
    return f"{key_prefix(org_id, doc_id)}{uuid.uuid4()}-{safe_stem(filename)}.{EXTENSIONS[content_type]}"


def create_upload(s3, org_id, doc_id, filename: str, content_type: str) -> dict:
    """A presigned POST. S3 itself enforces the pinned content type and the size range."""
    key = object_key(org_id, doc_id, filename, content_type)
    post = s3.generate_presigned_post(
        Bucket=settings.s3_bucket,
        Key=key,
        Fields={"Content-Type": content_type},
        Conditions=[
            {"Content-Type": content_type},
            ["content-length-range", 1, settings.max_upload_bytes],
        ],
        ExpiresIn=settings.upload_url_ttl_seconds,
    )
    return {"key": key, "url": post["url"], "fields": post["fields"]}


def download_name(key: str) -> str:
    return _UUID_PREFIX.sub("", key.rsplit("/", 1)[-1]) or "file"


def read_object(s3, key: str) -> bytes:
    """The stored file's bytes, for server-side processing (the review pipeline reads contracts this way)."""
    return s3.get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read()


def create_download(s3, key: str) -> str:
    return s3.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": settings.s3_bucket,
            "Key": key,
            "ResponseContentDisposition": f'attachment; filename="{download_name(key)}"',
        },
        ExpiresIn=settings.download_url_ttl_seconds,
    )
