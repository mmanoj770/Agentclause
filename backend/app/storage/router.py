from uuid import UUID

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg.errors import UniqueViolation
from pydantic import BaseModel, Field

from app.audit import write_audit
from app.auth.dependencies import CurrentUser, get_current_user, require_role
from app.config import settings
from app.db import get_conn
from app.documents.service import get_document
from app.documents.states import DocState
from app.storage import s3 as storage

router = APIRouter(prefix="/documents/{doc_id}/files", tags=["files"])
startup_only = require_role("startup_user")

MAX_VERSION_ATTEMPTS = 5

# TODO(decision): every confirmed upload becomes a document_versions row, i.e. a new DRAFT of
# the contract. The frontend also uploads execution evidence (stamp-duty certificates), which
# is not a draft and would wrongly bump the version number. Evidence needs its own table or a
# `kind` on the upload; deliberately not solved here.


# Files may only change while the startup can still edit the contract.
UPLOAD_STATES = frozenset({DocState.DRAFTED, DocState.REVISION_IN_PROGRESS, DocState.LAWYER_COMMENTED})


def _require_uploadable(doc: dict) -> None:
    if doc["state"] not in UPLOAD_STATES:
        raise HTTPException(409, f"Files cannot be uploaded while the document is '{doc['state']}'")


class UploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str
    size: int


class ConfirmRequest(BaseModel):
    key: str = Field(min_length=1, max_length=1024)


@router.post("/upload-url")
def upload_url(doc_id: UUID, body: UploadRequest,
               user: CurrentUser = Depends(startup_only), conn=Depends(get_conn),
               s3=Depends(storage.get_s3)):
    doc = get_document(conn, doc_id, user)  # 404 outside the caller's org
    _require_uploadable(doc)
    if body.content_type not in settings.allowed_upload_types or body.content_type not in storage.EXTENSIONS:
        raise HTTPException(422, "Use a PDF, DOCX, PNG or JPEG file.")
    if not 0 < body.size <= settings.max_upload_bytes:
        raise HTTPException(422, "The file is empty or larger than 25 MB.")
    return storage.create_upload(s3, doc["org_id"], doc["id"], body.filename, body.content_type)


def _next_version(conn, doc_id, key: str) -> int:
    """Insert the next version, retrying when another request took the same number."""
    for _ in range(MAX_VERSION_ATTEMPTS):
        try:
            with conn.transaction():
                row = conn.execute(
                    "select coalesce(max(version_no), 0) + 1 as n from document_versions where document_id = %s",
                    (doc_id,),
                ).fetchone()
                return conn.execute(
                    """insert into document_versions (document_id, version_no, storage_key)
                       values (%s, %s, %s) returning version_no""",
                    (doc_id, row["n"], key),
                ).fetchone()["version_no"]
        except UniqueViolation:
            continue
    raise HTTPException(409, "Could not record the upload, please try again")


@router.post("/confirm")
def confirm(doc_id: UUID, body: ConfirmRequest,
            user: CurrentUser = Depends(startup_only), conn=Depends(get_conn),
            s3=Depends(storage.get_s3)):
    doc = get_document(conn, doc_id, user)
    _require_uploadable(doc)
    key = body.key
    prefix = storage.key_prefix(doc["org_id"], doc["id"])
    if not key.startswith(prefix) or len(key) == len(prefix) or ".." in key:
        raise HTTPException(422, "That file does not belong to this document")

    # Same key confirmed twice (a retried request) is one version, not two.
    existing = conn.execute(
        "select version_no from document_versions where document_id = %s and storage_key = %s",
        (doc_id, key),
    ).fetchone()
    if existing:
        return {"version_no": existing["version_no"]}

    try:
        head = s3.head_object(Bucket=settings.s3_bucket, Key=key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            raise HTTPException(422, "The file was not uploaded")
        raise HTTPException(502, "Could not check the uploaded file")
    size = head.get("ContentLength", 0)
    if not 0 < size <= settings.max_upload_bytes:
        raise HTTPException(422, "The file is empty or larger than 25 MB.")
    if head.get("ContentType") not in settings.allowed_upload_types:
        raise HTTPException(422, "Use a PDF, DOCX, PNG or JPEG file.")

    with conn.transaction():
        version_no = _next_version(conn, doc_id, key)
        write_audit(conn, document_id=doc_id, actor_id=user.id, actor_role=user.role,
                    action="file_uploaded",
                    details={"version_no": version_no, "storage_key": key, "size": size})
    return {"version_no": version_no}


@router.get("/download-url")
def download_url(doc_id: UUID, version_no: int | None = Query(None, ge=1),
                 user: CurrentUser = Depends(get_current_user), conn=Depends(get_conn),
                 s3=Depends(storage.get_s3)):
    get_document(conn, doc_id, user)  # org's startup_user or the assigned lawyer; else 404
    row = conn.execute(
        """select version_no, storage_key from document_versions
           where document_id = %s and (%s::int is null or version_no = %s)
           order by version_no desc limit 1""",
        (doc_id, version_no, version_no),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Version not found")
    return {
        "url": storage.create_download(s3, row["storage_key"]),
        "expires_in": settings.download_url_ttl_seconds,
        "version_no": row["version_no"],
    }
