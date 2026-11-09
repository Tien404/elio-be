"""T-SQL for courses, offerings, memberships and registrations. Never commits."""

from decimal import Decimal
from typing import Any

from app.domain.entities import (
    Course,
    CourseMembership,
    CourseOffering,
    CourseRegistration,
    CourseRole,
    CourseState,
    MembershipStatus,
    RegistrationStatus,
)
from app.infrastructure.db.sql import Sql, like_literal


def _course(row: dict[str, Any]) -> Course:
    return Course(
        course_id=row["course_id"],
        course_code=row["course_code"],
        course_name=row["course_name"],
        credits=row["credits"],
        description=row["description"],
    )


class CourseRepository:
    def __init__(self, sql: Sql):
        self.sql = sql

    # ----------------------------------------------------------------- courses
    def max_course_number(self, stem: str) -> int | None:
        """Highest 2-digit number used after `stem` (e.g. CS10 -> 01..99).

        UPDLOCK + HOLDLOCK lock the key range, so two admins creating courses with the
        same stem at once queue up instead of picking the same number.
        """
        return self.sql.scalar(
            """SELECT MAX(CAST(RIGHT(course_code, 2) AS INT))
               FROM dbo.courses WITH (UPDLOCK, HOLDLOCK)
               WHERE course_code LIKE ?""",
            stem + "[0-9][0-9]",
        )

    def insert_course(
        self, *, course_code: str, course_name: str, credits: Decimal, description: str | None
    ) -> Course:
        row = self.sql.one(
            """INSERT dbo.courses (course_code, course_name, credits, description)
               OUTPUT INSERTED.course_id, INSERTED.course_code, INSERTED.course_name,
                      INSERTED.credits, INSERTED.description
               VALUES (?, ?, ?, ?)""",
            course_code,
            course_name,
            credits,
            description,
        )
        return _course(row)

    def find_course(self, course_id: int) -> Course | None:
        row = self.sql.one(
            """SELECT course_id, course_code, course_name, credits, description
               FROM dbo.courses WHERE course_id = ?""",
            course_id,
        )
        return _course(row) if row else None

    def search_courses(
        self, *, code_prefix: str | None, name_part: str | None, offset: int, limit: int
    ) -> tuple[list[Course], int]:
        """Catalog page ordered by code. At most one of code_prefix / name_part is used."""
        where, params = "1 = 1", []
        if code_prefix:
            where, params = "course_code LIKE ?", [like_literal(code_prefix) + "%"]
        elif name_part:
            where, params = "course_name LIKE ?", ["%" + like_literal(name_part) + "%"]
        total = self.sql.scalar(f"SELECT COUNT(*) FROM dbo.courses WHERE {where}", *params)
        rows = self.sql.all(
            f"""SELECT course_id, course_code, course_name, credits, description
                FROM dbo.courses WHERE {where}
                ORDER BY course_code OFFSET ? ROWS FETCH NEXT ? ROWS ONLY""",
            *params,
            offset,
            limit,
        )
        return [_course(row) for row in rows], total

    def find_course_by_code(self, course_code: str) -> Course | None:
        row = self.sql.one(
            """SELECT course_id, course_code, course_name, credits, description
               FROM dbo.courses WHERE course_code = ?""",
            course_code,
        )
        return _course(row) if row else None

    # --------------------------------------------------------------- offerings
    def max_section_number(self, course_id: int, semester: str) -> int | None:
        """Highest numeric section of a course in a semester; locked like max_course_number."""
        return self.sql.scalar(
            """SELECT MAX(TRY_CAST(section_code AS INT))
               FROM dbo.course_offerings WITH (UPDLOCK, HOLDLOCK)
               WHERE course_id = ? AND semester = ?""",
            course_id,
            semester,
        )

    def insert_offering(
        self, *, course_id: int, semester: str, section_code: str, title: str, created_by: int
    ) -> CourseOffering:
        row = self.sql.one(
            """INSERT dbo.course_offerings
                   (course_id, semester, section_code, title, state, created_by)
               OUTPUT INSERTED.offering_id, INSERTED.course_id, INSERTED.semester,
                      INSERTED.section_code, INSERTED.title, INSERTED.state, INSERTED.version
               VALUES (?, ?, ?, ?, 'DRAFT', ?)""",
            course_id,
            semester,
            section_code,
            title,
            created_by,
        )
        return _offering(row)

    def update_offering(self, offering_id, data):
        self.sql.execute(
            """UPDATE dbo.course_offerings SET title=?, semester=?, section_code=?,
                   learning_information=?, state=?, join_code=?, join_code_enabled=?,
                   archived_at=CASE WHEN ?='ARCHIVED' THEN SYSUTCDATETIME() ELSE NULL END,
                   version=version+1 WHERE offering_id=?""",
            data["title"],
            data["semester"],
            data["sectionCode"],
            data["learningInformation"],
            data["status"],
            data["joinCode"],
            data["joinEnabled"],
            data["status"],
            offering_id,
        )

    def metadata(self, offering_id):
        return self.sql.one(
            "SELECT learning_information, join_code, join_code_enabled FROM dbo.course_offerings WHERE offering_id=?",
            offering_id,
        )

    def resolve_join_code(self, code):
        return self.sql.scalar(
            "SELECT offering_id FROM dbo.course_offerings WITH (UPDLOCK, HOLDLOCK) WHERE join_code=? AND join_code_enabled=1 AND state='OPEN'",
            code,
        )

    def has_unfinished_attempts(self, offering_id):
        return bool(
            self.sql.scalar(
                """SELECT COUNT(*) FROM dbo.quiz_attempts AS t
               JOIN dbo.activities AS a ON a.activity_id=t.quiz_id
               WHERE a.offering_id=? AND t.finalized_by IS NULL""",
                offering_id,
            )
        )

    # ----------------------------------------------------------- registrations
    def insert_registration(self, *, course_id: int, student_id: int) -> CourseRegistration:
        """New PENDING request; a second open request raises a unique violation."""
        row = self.sql.one(
            """INSERT dbo.course_registrations (course_id, student_id)
               OUTPUT INSERTED.registration_id, INSERTED.course_id, INSERTED.student_id,
                      INSERTED.status, INSERTED.requested_at, INSERTED.decided_by,
                      INSERTED.decided_at
               VALUES (?, ?)""",
            course_id,
            student_id,
        )
        return _registration(row)

    def list_registrations(
        self, *, status: str | None, offset: int, limit: int
    ) -> tuple[list[dict[str, Any]], int]:
        """Requests with their course and student, oldest first (review queue order)."""
        where, params = ("r.status = ?", [status]) if status else ("1 = 1", [])
        total = self.sql.scalar(
            f"SELECT COUNT(*) FROM dbo.course_registrations AS r WHERE {where}", *params
        )
        rows = self.sql.all(
            f"""SELECT {_REGISTRATION_COLUMNS}, {_COURSE_COLUMNS}, {_STUDENT_COLUMNS}
                {_REGISTRATION_FROM}
                WHERE {where}
                ORDER BY r.requested_at, r.registration_id
                OFFSET ? ROWS FETCH NEXT ? ROWS ONLY""",
            *params,
            offset,
            limit,
        )
        return rows, total

    def get_registration(self, registration_id: int) -> dict[str, Any] | None:
        """One request with course and student, row-locked for a decision."""
        return self.sql.one(
            f"""SELECT {_REGISTRATION_COLUMNS}, {_COURSE_COLUMNS}, {_STUDENT_COLUMNS}
                FROM dbo.course_registrations AS r WITH (UPDLOCK, ROWLOCK)
                JOIN dbo.courses AS c ON c.course_id = r.course_id
                JOIN dbo.users AS u ON u.user_id = r.student_id
                JOIN dbo.students AS s ON s.user_id = r.student_id
                WHERE r.registration_id = ?""",
            registration_id,
        )

    def save_decision(self, registration: CourseRegistration) -> CourseRegistration:
        row = self.sql.one(
            """UPDATE dbo.course_registrations
               SET status = ?, decided_by = ?, decided_at = SYSUTCDATETIME(),
                   version = version + 1
               OUTPUT INSERTED.registration_id, INSERTED.course_id, INSERTED.student_id,
                      INSERTED.status, INSERTED.requested_at, INSERTED.decided_by,
                      INSERTED.decided_at
               WHERE registration_id = ?""",
            str(registration.status),
            registration.decided_by,
            registration.registration_id,
        )
        return _registration(row)

    def lock_approved_registration(self, *, course_id: int, student_id: int) -> bool:
        """True if the student is approved for the course. Locks the row so two
        professors cannot put the same student into two classes at once."""
        return bool(
            self.sql.scalar(
                """SELECT COUNT(*) FROM dbo.course_registrations WITH (UPDLOCK, ROWLOCK)
                   WHERE course_id = ? AND student_id = ? AND status = 'APPROVED'""",
                course_id,
                student_id,
            )
        )

    def list_approved_students(self, course_id: int) -> list[dict[str, Any]]:
        """Approved for the course and not yet in any of its classes (the waiting list)."""
        return self.sql.all(
            f"""SELECT {_STUDENT_COLUMNS}, u.must_change_pwd
                FROM dbo.course_registrations AS r
                JOIN dbo.users AS u ON u.user_id = r.student_id
                JOIN dbo.students AS s ON s.user_id = r.student_id
                WHERE r.course_id = ? AND r.status = 'APPROVED' AND u.status = 'ACTIVE'
                  AND NOT EXISTS (
                      SELECT 1 FROM dbo.course_memberships AS m
                      JOIN dbo.course_offerings AS o ON o.offering_id = m.offering_id
                      WHERE o.course_id = r.course_id AND m.user_id = r.student_id
                        AND m.status = 'ACTIVE')
                ORDER BY u.full_name, u.user_id""",
            course_id,
        )

    def enrollment_candidates(self, course_id, offering_id, search, offset, limit):
        where = """u.role='STUDENT' AND u.status='ACTIVE'
          AND NOT EXISTS (SELECT 1 FROM dbo.course_memberships AS m JOIN dbo.course_offerings AS o ON o.offering_id=m.offering_id WHERE m.user_id=u.user_id AND ((o.course_id=? AND m.status='ACTIVE') OR o.offering_id=?))"""
        params = [course_id, offering_id]
        if search:
            where += " AND (u.full_name LIKE ? OR u.email LIKE ?)"
            params += ["%" + like_literal(search) + "%"] * 2
        total = self.sql.scalar(f"SELECT COUNT(*) FROM dbo.users AS u WHERE {where}", *params)
        rows = self.sql.all(
            f"SELECT u.user_id,u.full_name,u.status,u.role,u.must_change_pwd FROM dbo.users AS u WHERE {where} ORDER BY u.full_name,u.user_id OFFSET ? ROWS FETCH NEXT ? ROWS ONLY",
            *params,
            offset,
            limit,
        )
        return rows, total

    # ------------------------------------------------------------ classes
    def get_offering(self, offering_id: int, *, lock=False) -> CourseOffering | None:
        row = self.sql.one(
            f"SELECT {_OFFERING_COLUMNS} FROM dbo.course_offerings AS o {'WITH (UPDLOCK, HOLDLOCK)' if lock else ''} WHERE o.offering_id = ?",
            offering_id,
        )
        return _offering(row) if row else None

    def offering_summary(self, offering_id: int) -> dict[str, Any] | None:
        """Offering row + course code + lead membership id (Offering response)."""
        return self.sql.one(f"{_OFFERING_SUMMARY_SELECT} WHERE o.offering_id = ?", offering_id)

    def list_offerings(
        self, *, member_id: int | None, offset: int, limit: int
    ) -> tuple[list[dict[str, Any]], int]:
        """Classes where member_id is an active member; every class when member_id is None."""
        if member_id is None:
            where, params = "1 = 1", []
        else:
            where = """EXISTS (SELECT 1 FROM dbo.course_memberships AS me
                               WHERE me.offering_id = o.offering_id AND me.user_id = ?
                                 AND me.status = 'ACTIVE' AND (o.state <> 'DRAFT' OR me.course_role <> 'STUDENT'))"""
            params = [member_id]
        total = self.sql.scalar(
            f"SELECT COUNT(*) FROM dbo.course_offerings AS o WHERE {where}", *params
        )
        rows = self.sql.all(
            f"""{_OFFERING_SUMMARY_SELECT} WHERE {where}
                ORDER BY o.semester DESC, c.course_code, o.section_code
                OFFSET ? ROWS FETCH NEXT ? ROWS ONLY""",
            *params,
            offset,
            limit,
        )
        return rows, total

    # ------------------------------------------------------------- memberships
    def find_membership(self, offering_id: int, user_id: int) -> CourseMembership | None:
        row = self.sql.one(
            f"""SELECT {_MEMBERSHIP_COLUMNS} FROM dbo.course_memberships AS m
                WHERE m.offering_id = ? AND m.user_id = ?""",
            offering_id,
            user_id,
        )
        return _membership(row) if row else None

    def is_in_course(self, *, course_id: int, user_id: int) -> bool:
        """Active member of any class of the course."""
        return bool(
            self.sql.scalar(
                """SELECT COUNT(*) FROM dbo.course_memberships AS m
                   JOIN dbo.course_offerings AS o ON o.offering_id = m.offering_id
                   WHERE o.course_id = ? AND m.user_id = ? AND m.status = 'ACTIVE'""",
                course_id,
                user_id,
            )
        )

    def list_memberships(
        self, offering_id: int, *, offset: int, limit: int
    ) -> tuple[list[dict[str, Any]], int]:
        """Active roster: professor first, then students by name."""
        total = self.sql.scalar(
            """SELECT COUNT(*) FROM dbo.course_memberships
               WHERE offering_id = ? AND status = 'ACTIVE'""",
            offering_id,
        )
        rows = self.sql.all(
            f"""SELECT {_MEMBERSHIP_COLUMNS}, u.full_name, u.status AS account_status,
                       u.role AS account_role, u.must_change_pwd
                FROM dbo.course_memberships AS m
                JOIN dbo.users AS u ON u.user_id = m.user_id
                WHERE m.offering_id = ? AND m.status = 'ACTIVE'
                ORDER BY CASE m.course_role WHEN 'STUDENT' THEN 1 ELSE 0 END,
                         u.full_name, m.membership_id
                OFFSET ? ROWS FETCH NEXT ? ROWS ONLY""",
            offering_id,
            offset,
            limit,
        )
        return rows, total

    def insert_membership(
        self, *, offering_id: int, user_id: int, course_role: CourseRole
    ) -> CourseMembership:
        row = self.sql.one(
            """INSERT dbo.course_memberships (offering_id, user_id, course_role)
               OUTPUT INSERTED.membership_id, INSERTED.offering_id, INSERTED.user_id,
                      INSERTED.course_role, INSERTED.status, INSERTED.joined_at,
                      INSERTED.version
               VALUES (?, ?, ?)""",
            offering_id,
            user_id,
            str(course_role),
        )
        return _membership(row)


_COURSE_COLUMNS = "c.course_code, c.course_name, c.credits, c.description"
_STUDENT_COLUMNS = "u.user_id, u.full_name, u.email, s.student_code"
_REGISTRATION_COLUMNS = """r.registration_id, r.course_id, r.student_id, r.status,
    r.requested_at, r.decided_by, r.decided_at"""
_REGISTRATION_FROM = """FROM dbo.course_registrations AS r
    JOIN dbo.courses AS c ON c.course_id = r.course_id
    JOIN dbo.users AS u ON u.user_id = r.student_id
    JOIN dbo.students AS s ON s.user_id = r.student_id"""
_OFFERING_COLUMNS = """o.offering_id, o.course_id, o.semester, o.section_code, o.title,
    o.state, o.version"""
_OFFERING_SUMMARY_SELECT = f"""SELECT {_OFFERING_COLUMNS}, c.course_code,
        lead.membership_id AS lead_membership_id
    FROM dbo.course_offerings AS o
    JOIN dbo.courses AS c ON c.course_id = o.course_id
    LEFT JOIN dbo.course_memberships AS lead
        ON lead.offering_id = o.offering_id AND lead.course_role = 'PRIMARY_INSTRUCTOR'
       AND lead.status = 'ACTIVE'"""
_MEMBERSHIP_COLUMNS = """m.membership_id, m.offering_id, m.user_id, m.course_role, m.status,
    m.joined_at, m.version"""


def registration_from_row(row: dict[str, Any]) -> CourseRegistration:
    return _registration(row)


def course_from_row(row: dict[str, Any]) -> Course:
    return _course(row)


def offering_from_row(row: dict[str, Any]) -> CourseOffering:
    return _offering(row)


def membership_from_row(row: dict[str, Any]) -> CourseMembership:
    return _membership(row)


def _offering(row: dict[str, Any]) -> CourseOffering:
    return CourseOffering(
        offering_id=row["offering_id"],
        course_id=row["course_id"],
        semester=row["semester"],
        section_code=row["section_code"],
        title=row["title"],
        state=CourseState(row["state"]),
        version=row["version"],
    )


def _registration(row: dict[str, Any]) -> CourseRegistration:
    return CourseRegistration(
        registration_id=row["registration_id"],
        course_id=row["course_id"],
        student_id=row["student_id"],
        status=RegistrationStatus(row["status"]),
        requested_at=row["requested_at"],
        decided_by=row["decided_by"],
        decided_at=row["decided_at"],
    )


def _membership(row: dict[str, Any]) -> CourseMembership:
    return CourseMembership(
        membership_id=row["membership_id"],
        offering_id=row["offering_id"],
        user_id=row["user_id"],
        course_role=CourseRole(row["course_role"]),
        status=MembershipStatus(row["status"]),
        joined_at=row["joined_at"],
        version=row["version"],
    )
