from pathlib import Path
from typing import Any, Callable
from uuid import UUID

from psycopg.types.json import Jsonb

from app.agents.conversational.chat_service import ChatUser, DocumentInfo, TurnRecord


def _field(row: Any, name: str) -> Any:
    return row[name] if isinstance(row, dict) else getattr(row, name)


def _text(value: Any) -> str:
    return str(getattr(value, "value", value))


class SupabaseDocumentSource:
    def __init__(
        self,
        conn,
        current_user,
        get_document: Callable,
        read_object: Callable,
        s3_factory: Callable,
    ):
        self.conn = conn
        self.current_user = current_user
        self.get_document = get_document
        self.read_object = read_object
        self.s3_factory = s3_factory
        self._allowed_keys: set[str] = set()

    def load_document(self, document_id: UUID, user: ChatUser) -> DocumentInfo:
        document = self.get_document(self.conn, document_id, self.current_user)
        row = self.conn.execute(
            "select id, storage_key from document_versions "
            "where document_id = %s order by version_no desc limit 1",
            (document_id,),
        ).fetchone()
        key = (row["storage_key"] if row else None) or ""
        if key:
            self._allowed_keys.add(key)
        return DocumentInfo(
            document_id=document_id,
            state=_text(_field(document, "state")),
            version_id=str(row["id"]) if row else "none",
            storage_key=key,
            filename=Path(key).name or None,
        )

    def read_file(self, storage_key: str) -> bytes:
        if storage_key not in self._allowed_keys:
            raise PermissionError("storage key was not issued for this request")
        return self.read_object(self.s3_factory(), storage_key)


class SupabaseChatLog:
    def __init__(self, conn, audit: Callable):
        self.conn = conn
        self.audit = audit

    def save_escalation(self, document_id: UUID, question: str, asked_by: str) -> UUID:
        with self.conn.transaction():
            row = self.conn.execute(
                "insert into chat_escalations (document_id, asked_by, question) "
                "values (%s, %s, %s) returning id",
                (document_id, asked_by, question),
            ).fetchone()
        return UUID(str(row["id"]))

    def save_turn(self, record: TurnRecord) -> None:
        version = None if record.document_version_id in (None, "none") else record.document_version_id
        with self.conn.transaction():
            self.conn.execute(
                "insert into chat_turns (id, document_id, document_version_id, asked_by, "
                "question, answer, status, reason, stage, classifier_source, attempts, "
                "retrieval_score, citations, escalation_id, latency_ms) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    record.turn_id,
                    record.document_id,
                    version,
                    record.asked_by,
                    record.question,
                    record.answer,
                    record.status,
                    record.reason,
                    record.stage,
                    record.classifier_source,
                    record.attempts,
                    record.retrieval_score,
                    Jsonb(record.citations),
                    record.escalation_id,
                    record.latency_ms,
                ),
            )

    def write_audit(self, document_id: UUID, user: ChatUser, action: str, details: dict) -> None:
        with self.conn.transaction():
            self.audit(
                self.conn,
                document_id=document_id,
                actor_id=user.id,
                actor_role=user.role,
                action=action,
                details=details,
            )
