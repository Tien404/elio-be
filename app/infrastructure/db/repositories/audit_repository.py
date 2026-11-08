import json
from typing import Any

from app.infrastructure.db.sql import Sql


class AuditRepository:
    """Append-only audit trail. Callers must never pass passwords, tokens, scores or feedback."""

    def __init__(self, sql: Sql):
        self.sql = sql

    def record(
        self,
        *,
        actor_id: int,
        action: str,
        target_type: str,
        target_id: int,
        reason: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.sql.execute(
            """INSERT dbo.audit_entries (actor_id, action_type, target_type, target_id, reason, details)
               VALUES (?, ?, ?, ?, ?, ?)""",
            actor_id,
            action,
            target_type,
            target_id,
            reason,
            json.dumps(details or {}, separators=(",", ":")),
        )
