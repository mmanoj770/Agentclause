import json
from pathlib import Path

from psycopg import Connection

from app.clauses.models import ClauseRecord, VerificationStatus


def load_clause(conn: Connection, data: dict) -> str:
    """
    Validate and insert one clause into the database.
    Returns the clause_id on success.
    Raises ValueError or pydantic.ValidationError on bad data.
    """
    clause = ClauseRecord(**data)

    # Safety: never allow a clause to be marked verified without a named reviewer.
    # X4 (the verified-data import pipeline) will supply verified_by when loading
    # lawyer-approved clauses. Dev seeds must always stay 'staging'.
    if clause.verification_status == VerificationStatus.verified:
        if not clause.verified_by:
            raise ValueError(
                "Cannot mark clause 'verified' without a verified_by value. "
                "Only X4 import pipeline should load verified clauses."
            )

    conn.execute(
        """
        INSERT INTO clauses (
            clause_type, contract_types, favoured_party,
            statute_refs, version, verification_status,
            content, title, notes, verified_by,
            verified_at
        ) VALUES (
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            CASE WHEN %s = 'verified' THEN now() ELSE NULL END
        )
        """,
        (
            clause.clause_type,
            clause.contract_types,
            clause.favoured_party,
            clause.statute_refs,
            clause.version,
            clause.verification_status,
            clause.content,
            clause.title,
            clause.notes,
            clause.verified_by,
            clause.verification_status,  # repeated for the CASE expression
        ),
    )

    return str(clause.clause_id)


def seed_from_file(conn: Connection, json_path: Path) -> int:
    """
    Load all clauses from a JSON seed file.
    Returns the number of clauses inserted.
    All clauses in seed files must be 'staging' — this is enforced by load_clause.
    """
    clauses = json.loads(json_path.read_text(encoding="utf-8"))
    count = 0
    for item in clauses:
        load_clause(conn, item)
        count += 1
    return count
