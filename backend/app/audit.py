from psycopg.types.json import Jsonb


def write_audit(conn, *, document_id, actor_id, actor_role, action, details=None):
    conn.execute(
        """insert into audit_logs (document_id, actor_id, actor_role, action, details)
           values (%s, %s, %s, %s, %s)""",
        (document_id, actor_id, actor_role, action, Jsonb(details or {})),
    )
