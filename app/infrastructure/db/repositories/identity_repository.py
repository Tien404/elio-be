"""T-SQL for users, role subtypes and sessions. Never commits; caller owns the transaction."""

from datetime import datetime
from typing import Any

from app.infrastructure.db.sql import Sql

_ACCOUNT_COLUMNS = """
    u.user_id, u.email, u.full_name, u.password_hash, u.role, u.status,
    u.must_change_pwd, u.created_at, u.version,
    CAST(COALESCE(i.can_create_course, 0) AS BIT) AS can_create_course
"""
_ACCOUNT_FROM = """
    FROM dbo.users AS u
    LEFT JOIN dbo.instructors AS i ON i.user_id = u.user_id
"""


class IdentityRepository:
    def __init__(self, sql: Sql):
        self.sql = sql

    # ---------------------------------------------------------------- accounts
    def find_by_email(self, email: str) -> dict[str, Any] | None:
        return self.sql.one(f"SELECT {_ACCOUNT_COLUMNS} {_ACCOUNT_FROM} WHERE u.email = ?", email)

    def get_account(self, user_id: int, *, lock: bool = False) -> dict[str, Any] | None:
        hint = "WITH (UPDLOCK, ROWLOCK)" if lock else ""
        return self.sql.one(
            f"""SELECT {_ACCOUNT_COLUMNS}
                FROM dbo.users AS u {hint}
                LEFT JOIN dbo.instructors AS i ON i.user_id = u.user_id
                WHERE u.user_id = ?""",
            user_id,
        )

    def first_admin_id(self) -> int | None:
        return self.sql.scalar("SELECT MIN(user_id) FROM dbo.admins")

    def count_admins(self) -> int:
        return self.sql.scalar("SELECT COUNT(*) FROM dbo.admins WITH (UPDLOCK, HOLDLOCK)")

    def insert_user(
        self,
        *,
        email: str,
        full_name: str,
        password_hash: str,
        role: str,
        must_change_pwd: bool,
        created_by: int | None,
    ) -> int:
        return self.sql.scalar(
            """INSERT dbo.users (email, full_name, password_hash, role, must_change_pwd, created_by)
               OUTPUT INSERTED.user_id
               VALUES (?, ?, ?, ?, ?, ?)""",
            email,
            full_name,
            password_hash,
            role,
            must_change_pwd,
            created_by,
        )

    def insert_student(self, user_id: int) -> None:
        # Contract gap: CreateAccountRequest carries no student code; derive a stable one.
        self.sql.execute(
            "INSERT dbo.students (user_id, student_code) VALUES (?, CONCAT(N'S', FORMAT(?, '000000')))",
            user_id,
            user_id,
        )

    def insert_instructor(self, user_id: int, can_create_course: bool) -> None:
        self.sql.execute(
            "INSERT dbo.instructors (user_id, can_create_course) VALUES (?, ?)",
            user_id,
            can_create_course,
        )

    def insert_admin(self, user_id: int) -> None:
        self.sql.execute("INSERT dbo.admins (user_id) VALUES (?)", user_id)

    def update_display_name(self, user_id: int, full_name: str) -> None:
        self.sql.execute(
            "UPDATE dbo.users SET full_name = ?, version = version + 1 WHERE user_id = ?",
            full_name,
            user_id,
        )

    def update_password(self, user_id: int, password_hash: str, *, must_change: bool) -> None:
        self.sql.execute(
            """UPDATE dbo.users
               SET password_hash = ?, must_change_pwd = ?, version = version + 1
               WHERE user_id = ?""",
            password_hash,
            must_change,
            user_id,
        )

    def update_status(self, user_id: int, status: str) -> None:
        self.sql.execute(
            "UPDATE dbo.users SET status = ?, version = version + 1 WHERE user_id = ?",
            status,
            user_id,
        )

    def update_can_create_course(self, user_id: int, value: bool) -> None:
        self.sql.execute(
            "UPDATE dbo.instructors SET can_create_course = ? WHERE user_id = ?", value, user_id
        )
        self.sql.execute("UPDATE dbo.users SET version = version + 1 WHERE user_id = ?", user_id)

    def count_open_leaderships(self, user_id: int) -> int:
        """Active lead memberships in DRAFT/OPEN offerings (must be transferred before locking)."""
        return self.sql.scalar(
            """SELECT COUNT(*)
               FROM dbo.course_memberships AS m
               JOIN dbo.course_offerings AS o ON o.offering_id = m.offering_id
               WHERE m.user_id = ? AND m.course_role = 'PRIMARY_INSTRUCTOR'
                 AND m.status = 'ACTIVE' AND o.state IN ('DRAFT', 'OPEN')""",
            user_id,
        )

    def list_accounts(
        self,
        *,
        q: str | None,
        status: str | None,
        can_create_course: bool | None,
        offset: int,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        where = ["1 = 1"]
        params: list[Any] = []
        if q:
            where.append("(u.email LIKE ? OR u.full_name LIKE ?)")
            pattern = "%" + q.replace("[", "[[]").replace("%", "[%]").replace("_", "[_]") + "%"
            params += [pattern, pattern]
        if status:
            where.append("u.status = ?")
            params.append(status)
        if can_create_course is not None:
            where.append("COALESCE(i.can_create_course, 0) = ?")
            params.append(can_create_course)
        clause = " AND ".join(where)
        total = self.sql.scalar(f"SELECT COUNT(*) {_ACCOUNT_FROM} WHERE {clause}", *params)
        rows = self.sql.all(
            f"""SELECT {_ACCOUNT_COLUMNS} {_ACCOUNT_FROM} WHERE {clause}
                ORDER BY u.user_id OFFSET ? ROWS FETCH NEXT ? ROWS ONLY""",
            *params,
            offset,
            limit,
        )
        return rows, total

    # ---------------------------------------------------------------- sessions
    def insert_session(
        self, *, user_id: int, token_hash: str, ttl_hours: int, restricted: bool
    ) -> dict[str, Any]:
        return self.sql.one(
            """DECLARE @now DATETIMEOFFSET(7) = SYSUTCDATETIME();
               INSERT dbo.user_sessions (user_id, token_hash, issued_at, expires_at, restricted)
               OUTPUT INSERTED.session_id, INSERTED.expires_at
               VALUES (?, ?, @now, DATEADD(HOUR, ?, @now), ?)""",
            user_id,
            token_hash,
            ttl_hours,
            restricted,
        )

    def find_live_session(self, token_hash: str) -> dict[str, Any] | None:
        """Unrevoked, unexpired session of an ACTIVE account (DB clock decides expiry)."""
        return self.sql.one(
            """SELECT s.session_id, s.user_id, s.expires_at, s.restricted, u.role
               FROM dbo.user_sessions AS s
               JOIN dbo.users AS u ON u.user_id = s.user_id
               WHERE s.token_hash = ? AND s.revoked_at IS NULL
                 AND s.expires_at > SYSUTCDATETIME() AND u.status = 'ACTIVE'""",
            token_hash,
        )

    def revoke_session(self, session_id: int) -> None:
        self.sql.execute(
            """UPDATE dbo.user_sessions SET revoked_at = SYSUTCDATETIME()
               WHERE session_id = ? AND revoked_at IS NULL""",
            session_id,
        )

    def revoke_all_sessions(self, user_id: int) -> int:
        return self.sql.execute(
            """UPDATE dbo.user_sessions SET revoked_at = SYSUTCDATETIME()
               WHERE user_id = ? AND revoked_at IS NULL""",
            user_id,
        )


def account_view(row: dict[str, Any]) -> dict[str, Any]:
    """MeView mapping shared by /me and admin account endpoints."""
    return {
        "account": {
            "id": row["user_id"],
            "displayName": row["full_name"],
            "status": row["status"],
            "role": row["role"],
            "mustChangePassword": bool(row["must_change_pwd"]),
        },
        "email": row["email"],
        "canCreateCourse": bool(row["can_create_course"]),
        "version": row["version"],
    }


def utc_iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")
