"MySQL SQL for users, role subtypes and sessions. Never commits; caller owns the transaction."

from datetime import datetime
from typing import Any

from app.domain.entities import AccountStatus, SystemRole, User
from app.infrastructure.db.connection import DatabaseUnavailable
from app.infrastructure.db.sql import Sql, like_literal

_ACCOUNT_COLUMNS = """
    u.user_id, u.email, u.full_name, u.password_hash, u.role, u.status,
    u.must_change_pwd, u.created_at, u.version,
    COALESCE(i.can_create_course, 0) AS can_create_course
"""
_ACCOUNT_FROM = """
    FROM users AS u
    LEFT JOIN instructors AS i ON i.user_id = u.user_id
"""


class IdentityRepository:
    def __init__(self, sql: Sql):
        self.sql = sql

    # ---------------------------------------------------------------- accounts
    def find_by_email(self, email: str) -> dict[str, Any] | None:
        return self.sql.one(f"SELECT {_ACCOUNT_COLUMNS} {_ACCOUNT_FROM} WHERE u.email = %s", email)

    def get_account(self, user_id: int, *, lock: bool = False) -> dict[str, Any] | None:
        hint = "FOR UPDATE" if lock else ""
        return self.sql.one(
            f"""SELECT {_ACCOUNT_COLUMNS}
                FROM users AS u
                LEFT JOIN instructors AS i ON i.user_id = u.user_id
                WHERE u.user_id = %s {hint}""",
            user_id,
        )

    def first_admin_id(self) -> int | None:
        return self.sql.scalar("SELECT MIN(user_id) FROM admins")

    def count_admins(self) -> int:
        if self.sql.scalar("SELECT GET_LOCK('elio:bootstrap-admin', 2)") != 1:
            raise DatabaseUnavailable("Account initialization is busy.")
        return self.sql.scalar("SELECT COUNT(*) FROM admins")

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
        return self.sql.insert(
            """INSERT INTO users (email, full_name, password_hash, role, must_change_pwd, created_by)

               VALUES (%s, %s, %s, %s, %s, %s)""",
            email,
            full_name,
            password_hash,
            role,
            must_change_pwd,
            created_by,
        )

    def insert_student(self, user_id: int) -> None:
        # Derive a stable student code from the account ID.
        self.sql.execute(
            "INSERT INTO students (user_id, student_code) VALUES (%s, CONCAT('S', LPAD(%s, 6, '0')))",
            user_id,
            user_id,
        )

    def insert_instructor(self, user_id: int, can_create_course: bool) -> None:
        self.sql.execute(
            "INSERT INTO instructors (user_id, can_create_course) VALUES (%s, %s)",
            user_id,
            can_create_course,
        )

    def insert_admin(self, user_id: int) -> None:
        self.sql.execute("INSERT INTO admins (user_id) VALUES (%s)", user_id)

    def update_display_name(self, user_id: int, full_name: str) -> None:
        self.sql.execute(
            "UPDATE users SET full_name = %s, version = version + 1 WHERE user_id = %s",
            full_name,
            user_id,
        )

    def update_password(self, user_id: int, password_hash: str, *, must_change: bool) -> None:
        self.sql.execute(
            """UPDATE users
               SET password_hash = %s, must_change_pwd = %s, version = version + 1
               WHERE user_id = %s""",
            password_hash,
            must_change,
            user_id,
        )

    def update_status(self, user_id: int, status: str) -> None:
        self.sql.execute(
            "UPDATE users SET status = %s, version = version + 1 WHERE user_id = %s",
            status,
            user_id,
        )

    def update_can_create_course(self, user_id: int, value: bool) -> None:
        self.sql.execute(
            "UPDATE instructors SET can_create_course = %s WHERE user_id = %s", value, user_id
        )
        self.sql.execute("UPDATE users SET version = version + 1 WHERE user_id = %s", user_id)

    def count_open_leaderships(self, user_id: int) -> int:
        """Active lead memberships in DRAFT/OPEN offerings (must be transferred before locking)."""
        return self.sql.scalar(
            """SELECT COUNT(*)
               FROM course_memberships AS m
               JOIN course_offerings AS o ON o.offering_id = m.offering_id
               WHERE m.user_id = %s AND m.course_role = 'PRIMARY_INSTRUCTOR'
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
            where.append("(u.email LIKE %s ESCAPE '!' OR u.full_name LIKE %s ESCAPE '!')")
            pattern = "%" + like_literal(q) + "%"
            params += [pattern, pattern]
        if status:
            where.append("u.status = %s")
            params.append(status)
        if can_create_course is not None:
            where.append("COALESCE(i.can_create_course, 0) = %s")
            params.append(can_create_course)
        clause = " AND ".join(where)
        total = self.sql.scalar(f"SELECT COUNT(*) {_ACCOUNT_FROM} WHERE {clause}", *params)
        rows = self.sql.all(
            f"""SELECT {_ACCOUNT_COLUMNS} {_ACCOUNT_FROM} WHERE {clause}
                ORDER BY u.user_id LIMIT %s, %s""",
            *params,
            offset,
            limit,
        )
        return rows, total

    # ---------------------------------------------------------------- sessions
    def insert_session(
        self, *, user_id: int, token_hash: str, ttl_hours: int, restricted: bool
    ) -> dict[str, Any]:
        inserted_id = self.sql.insert(
            """
               INSERT INTO user_sessions (user_id, token_hash, issued_at, expires_at, restricted)

               VALUES (%s, %s, UTC_TIMESTAMP(6), DATE_ADD(UTC_TIMESTAMP(6), INTERVAL %s HOUR), %s)""",
            user_id,
            token_hash,
            ttl_hours,
            restricted,
        )
        return self.sql.one(
            "SELECT session_id, expires_at FROM user_sessions WHERE session_id = %s", inserted_id
        )

    def find_live_session(self, token_hash: str) -> dict[str, Any] | None:
        """Unrevoked, unexpired session of an ACTIVE account (DB clock decides expiry)."""
        return self.sql.one(
            """SELECT s.session_id, s.user_id, s.expires_at, s.restricted, u.role
               FROM user_sessions AS s
               JOIN users AS u ON u.user_id = s.user_id
               WHERE s.token_hash = %s AND s.revoked_at IS NULL
                 AND s.expires_at > UTC_TIMESTAMP(6) AND u.status = 'ACTIVE'""",
            token_hash,
        )

    def revoke_session(self, session_id: int) -> None:
        self.sql.execute(
            """UPDATE user_sessions SET revoked_at = UTC_TIMESTAMP(6)
               WHERE session_id = %s AND revoked_at IS NULL""",
            session_id,
        )

    def revoke_all_sessions(self, user_id: int) -> int:
        return self.sql.execute(
            """UPDATE user_sessions SET revoked_at = UTC_TIMESTAMP(6)
               WHERE user_id = %s AND revoked_at IS NULL""",
            user_id,
        )


def user_from_row(row: dict[str, Any]) -> User:
    return User(
        user_id=row["user_id"],
        email=row["email"],
        full_name=row["full_name"],
        password_hash=row["password_hash"],
        role=SystemRole(row["role"]),
        status=AccountStatus(row["status"]),
        must_change_password=bool(row["must_change_pwd"]),
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
