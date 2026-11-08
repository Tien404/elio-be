from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(frozen=True)
class Actor:
    user_id: int
    role: Literal["STUDENT", "INSTRUCTOR", "ADMIN"]
    restricted: bool = False


@dataclass(frozen=True)
class SessionContext:
    """Resolved cookie session for one request. `token` is the raw cookie value (never logged)."""

    actor: Actor
    session_id: int
    token: str
    expires_at: datetime
