"""Real S3 round trip for the file routes' presign helper. No database, no API server.

    cd backend && python ../scripts/s3_smoke.py [--skip-expiry]

Reads S3_BUCKET, AWS_REGION and credentials from .env.local (or the standard AWS chain),
through the same app.config.settings and app.storage.s3 helpers the routes use.

Needs `requests` (pip install requests). Prints PASS/FAIL per step and never prints keys,
signed URLs or the object key; failures show only an error class or status code.
The test object lives under orgs/smoke-test/ and is deleted at the end.
"""
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

try:
    import requests
except ImportError:
    sys.exit("This script needs requests: pip install requests")

import boto3  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402

from app.config import ROOT, settings  # noqa: E402
from app.storage import s3 as storage  # noqa: E402

PDF = "application/pdf"
failures = 0


def report(name: str, ok: bool, detail: str = "") -> bool:
    global failures
    failures += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    return ok


def sample_pdf() -> bytes:
    # A tiny but valid one-page PDF, with a random marker so each run's bytes are unique.
    body = f"BT /F1 12 Tf 20 100 Td (smoke {uuid.uuid4()}) Tj ET".encode()
    return (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Contents 4 0 R>>endobj\n"
            b"4 0 obj<</Length " + str(len(body)).encode() + b">>stream\n" + body +
            b"\nendstream endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")


def main() -> int:
    skip_expiry = "--skip-expiry" in sys.argv
    print(f"settings file: {'found' if (ROOT / '.env.local').exists() else 'NOT FOUND'} (.env.local)")
    if not report("bucket configured", bool(settings.s3_bucket),
                  "" if settings.s3_bucket else "set S3_BUCKET in .env.local"):
        return 1
    have_keys = bool(settings.aws_access_key_id and settings.aws_secret_access_key)
    if not report("credentials found", have_keys or boto3.Session().get_credentials() is not None,
                  "" if have_keys else "none in .env.local or the AWS chain"):
        return 1
    client = storage._client()
    data = sample_pdf()
    key = None
    try:
        # 1. presigned POST, built by the same helper the upload-url route uses
        try:
            post = storage.create_upload(client, "smoke-test", uuid.uuid4(), "smoke.pdf", PDF)
            key = post["key"]
            report("generate presigned POST", True)
        except Exception as exc:
            report("generate presigned POST", False, type(exc).__name__)
            return 1

        # 2. upload with requests: signed fields first, the file last (S3 requires it)
        try:
            r = requests.post(post["url"], data=post["fields"],
                              files={"file": ("smoke.pdf", data, PDF)}, timeout=30)
            if not report("upload PDF", r.status_code in (200, 201, 204), f"HTTP {r.status_code}"):
                return 1
        except requests.RequestException as exc:
            report("upload PDF", False, type(exc).__name__)
            return 1

        # 3. the object exists with the pinned type and the right size
        try:
            head = client.head_object(Bucket=settings.s3_bucket, Key=key)
            report("object exists", head["ContentLength"] == len(data) and head["ContentType"] == PDF,
                   f"{head['ContentLength']} bytes, {head['ContentType']}")
        except ClientError as exc:
            report("object exists", False, exc.response.get("Error", {}).get("Code", "error"))
            return 1

        # 4. presigned GET, default 5-minute TTL, and the bytes match
        try:
            url = storage.create_download(client, key)
            r = requests.get(url, timeout=30)
            report("download via presigned GET", r.status_code == 200, f"HTTP {r.status_code}")
            report("downloaded bytes match", r.content == data)
            report("download is an attachment", "attachment" in r.headers.get("Content-Disposition", ""))
        except Exception as exc:
            report("download via presigned GET", False, type(exc).__name__)

        # 5. a 5-second link stops working
        if skip_expiry:
            print("SKIP  expiry check (--skip-expiry)")
        else:
            previous = settings.download_url_ttl_seconds
            try:
                settings.download_url_ttl_seconds = 5
                short = storage.create_download(client, key)
            finally:
                settings.download_url_ttl_seconds = previous
            try:
                fresh = requests.get(short, timeout=30)
                report("5s link works before expiry", fresh.status_code == 200, f"HTTP {fresh.status_code}")
                time.sleep(6)
                late = requests.get(short, timeout=30)
                report("5s link returns 403 after 6s", late.status_code == 403, f"HTTP {late.status_code}")
            except Exception as exc:
                report("expiry check", False, type(exc).__name__)
    finally:
        # 6. clean up. The app's IAM policy may deny delete (docs/storage/app-iam-policy.json),
        # and a versioned bucket keeps the old version behind a delete marker.
        if key:
            try:
                client.delete_object(Bucket=settings.s3_bucket, Key=key)
                report("delete test object", True, "if the bucket is versioned, a delete marker remains")
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "error")
                report("delete test object", False,
                       f"{code}; remove orgs/smoke-test/ by hand with an admin profile")
    print("ALL PASS" if failures == 0 else f"{failures} step(s) FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
