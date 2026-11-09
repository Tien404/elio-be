"MySQL SQL for courses, offerings, memberships and registrations. Never commits."

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
from app.infrastructure.db.connection import DatabaseUnavailable
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
        # Serialize code allocation for this prefix; closing the connection releases the lock.
        if self.sql.scalar("SELECT GET_LOCK(%s, 2)", "elio:course:" + stem) != 1:
            raise DatabaseUnavailable("Course code allocation is busy.")
        return self.sql.scalar(
            """SELECT MAX(CAST(RIGHT(course_code, 2) AS UNSIGNED))
               FROM courses
               WHERE course_code LIKE %s ESCAPE '!' FOR UPDATE""",
            stem + "__",
        )

    def insert_course(
        self, *, course_code: str, course_name: str, credits: Decimal, description: str | None
    ) -> Course:
        inserted_id = self.sql.insert(
            """INSERT INTO courses (course_code, course_name, credits, description)

               VALUES (%s, %s, %s, %s)""",
            course_code,
            course_name,
            credits,
            description,
        )
        row = self.sql.one(
            """SELECT course_id, course_code, course_name,
                      credits, description FROM courses WHERE course_id = %s""",
            inserted_id,
        )
        return _course(row)

    def find_course(self, course_id: int) -> Course | None:
        row = self.sql.one(
            """SELECT course_id, course_code, course_name, credits, description
               FROM courses WHERE course_id = %s""",
            course_id,
        )
        return _course(row) if row else None

    def search_courses(
        self, *, code_prefix: str | None, name_part: str | None, offset: int, limit: int
    ) -> tuple[list[Course], int]:
        """Catalog page ordered by code. At most one of code_prefix / name_part is used."""
        where, params = "1 = 1", []
        if code_prefix:
            where, params = "course_code LIKE %s ESCAPE '!'", [like_literal(code_prefix) + "%"]
        elif name_part:
            where, params = "course_name LIKE %s ESCAPE '!'", ["%" + like_literal(name_part) + "%"]
        total = self.sql.scalar(f"SELECT COUNT(*) FROM courses WHERE {where}", *params)
        rows = self.sql.all(
            f"""SELECT course_id, course_code, course_name, credits, description
                FROM courses WHERE {where}
                ORDER BY course_code LIMIT %s, %s""",
            *params,
            offset,
            limit,
        )
        return [_course(row) for row in rows], total

    def find_course_by_code(self, course_code: str) -> Course | None:
        row = self.sql.one(
            """SELECT course_id, course_code, course_name, credits, description
               FROM courses WHERE course_code = %s""",
            course_code,
        )
        return _course(row) if row else None

    # --------------------------------------------------------------- offerings
    def max_section_number(self, course_id: int, semester: str) -> int | None:
        """Highest numeric section of a course in a semester; locked like max_course_number."""
        return self.sql.scalar(
            """SELECT MAX(CASE WHEN section_code REGEXP '^[0-9]+$' THEN CAST(section_code AS UNSIGNED) END)
               FROM course_offerings
               WHERE course_id = %s AND semester = %s FOR UPDATE""",
            course_id,
            semester,
        )

    def insert_offering(
        self, *, course_id: int, semester: str, section_code: str, title: str, created_by: int
    ) -> CourseOffering:
        inserted_id = self.sql.insert(
            """INSERT INTO course_offerings
                   (course_id, semester, section_code, title, state, created_by)

               VALUES (%s, %s, %s, %s, 'DRAFT', %s)""",
            course_id,
            semester,
            section_code,
            title,
            created_by,
        )
        row = self.sql.one(
            """SELECT offering_id, course_id, semester,
                      section_code, title, state, version FROM course_offerings WHERE offering_id = %s""",
            inserted_id,
        )
        return _offering(row)

    def update_offering(self, offering_id, data):
        self.sql.execute(
            """UPDATE course_offerings SET title=%s, semester=%s, section_code=%s,
                   learning_information=%s, state=%s, join_code=%s, join_code_enabled=%s,
                   archived_at=CASE WHEN %s='ARCHIVED' THEN UTC_TIMESTAMP(6) ELSE NULL END,
                   version=version+1 WHERE offering_id=%s""",
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
            "SELECT learning_information, join_code, join_code_enabled FROM course_offerings WHERE offering_id=%s",
            offering_id,
        )

    def resolve_join_code(self, code):
        return self.sql.scalar(
            "SELECT offering_id FROM course_offerings  WHERE join_code=%s AND join_code_enabled=1 AND state='OPEN' FOR UPDATE",
            code,
        )

    def has_unfinished_attempts(self, offering_id):
        return bool(
            self.sql.scalar(
                """SELECT COUNT(*) FROM quiz_attempts AS t
               JOIN activities AS a ON a.activity_id=t.quiz_id
               WHERE a.offering_id=%s AND t.finalized_by IS NULL""",
                offering_id,
            )
        )

    # ----------------------------------------------------------- registrations
    def insert_registration(self, *, course_id: int, student_id: int) -> CourseRegistration:
        """New PENDING request; a second open request raises a unique violation."""
        inserted_id = self.sql.insert(
            """INSERT INTO course_registrations (course_id, student_id)

               VALUES (%s, %s)""",
            course_id,
            student_id,
        )
        row = self.sql.one(
            """SELECT registration_id, course_id, student_id,
                      status, requested_at, decided_by,
                      decided_at FROM course_registrations WHERE registration_id = %s""",
            inserted_id,
        )
        return _registration(row)

    def list_registrations(
        self, *, status: str | None, offset: int, limit: int
    ) -> tuple[list[dict[str, Any]], int]:
        """Requests with their course and student, oldest first (review queue order)."""
        where, params = ("r.status = %s", [status]) if status else ("1 = 1", [])
        total = self.sql.scalar(
            f"SELECT COUNT(*) FROM course_registrations AS r WHERE {where}", *params
        )
        rows = self.sql.all(
            f"""SELECT {_REGISTRATION_COLUMNS}, {_COURSE_COLUMNS}, {_STUDENT_COLUMNS}
                {_REGISTRATION_FROM}
                WHERE {where}
                ORDER BY r.requested_at, r.registration_id
                LIMIT %s, %s""",
            *params,
            offset,
            limit,
        )
        return rows, total

    def get_registration(self, registration_id: int) -> dict[str, Any] | None:
        """One request with course and student, row-locked for a decision."""
        return self.sql.one(
            f"""SELECT {_REGISTRATION_COLUMNS}, {_COURSE_COLUMNS}, {_STUDENT_COLUMNS}
                FROM course_registrations AS r
                JOIN courses AS c ON c.course_id = r.course_id
                JOIN users AS u ON u.user_id = r.student_id
                JOIN students AS s ON s.user_id = r.student_id
                WHERE r.registration_id = %s FOR UPDATE""",
            registration_id,
        )

    def save_decision(self, registration: CourseRegistration) -> CourseRegistration:
        self.sql.execute(
            """UPDATE course_registrations
               SET status = %s, decided_by = %s, decided_at = UTC_TIMESTAMP(6),
                   version = version + 1

               WHERE registration_id = %s""",
            str(registration.status),
            registration.decided_by,
            registration.registration_id,
        )
        row = self.sql.one(
            """SELECT registration_id, course_id, student_id,
                      status, requested_at, decided_by,
                      decided_at FROM course_registrations WHERE registration_id = %s""",
            registration.registration_id,
        )
        return _registration(row)

    def lock_approved_registration(self, *, course_id: int, student_id: int) -> bool:
        """True if the student is approved for the course. Locks the row so two
        professors cannot put the same student into two classes at once."""
        return bool(
            self.sql.scalar(
                """SELECT COUNT(*) FROM course_registrations
                   WHERE course_id = %s AND student_id = %s AND status = 'APPROVED' FOR UPDATE""",
                course_id,
                student_id,
            )
        )

    def list_approved_students(self, course_id: int) -> list[dict[str, Any]]:
        """Approved for the course and not yet in any of its classes (the waiting list)."""
        return self.sql.all(
            f"""SELECT {_STUDENT_COLUMNS}, u.must_change_pwd
                FROM course_registrations AS r
                JOIN users AS u ON u.user_id = r.student_id
                JOIN students AS s ON s.user_id = r.student_id
                WHERE r.course_id = %s AND r.status = 'APPROVED' AND u.status = 'ACTIVE'
                  AND NOT EXISTS (
                      SELECT 1 FROM course_memberships AS m
                      JOIN course_offerings AS o ON o.offering_id = m.offering_id
                      WHERE o.course_id = r.course_id AND m.user_id = r.student_id
                        AND m.status = 'ACTIVE')
                ORDER BY u.full_name, u.user_id""",
            course_id,
        )

    def enrollment_candidates(self, course_id, offering_id, search, offset, limit):
        where = """u.role='STUDENT' AND u.status='ACTIVE'
          AND NOT EXISTS (SELECT 1 FROM course_memberships AS m JOIN course_offerings AS o ON o.offering_id=m.offering_id WHERE m.user_id=u.user_id AND ((o.course_id=%s AND m.status='ACTIVE') OR o.offering_id=%s))"""
        params = [course_id, offering_id]
        if search:
            where += " AND (u.full_name LIKE %s ESCAPE '!' OR u.email LIKE %s ESCAPE '!')"
            params += ["%" + like_literal(search) + "%"] * 2
        total = self.sql.scalar(f"SELECT COUNT(*) FROM users AS u WHERE {where}", *params)
        rows = self.sql.all(
            f"SELECT u.user_id,u.full_name,u.status,u.role,u.must_change_pwd FROM users AS u WHERE {where} ORDER BY u.full_name,u.user_id LIMIT %s, %s",
            *params,
            offset,
            limit,
        )
        return rows, total

    # ------------------------------------------------------------ classes
    def get_offering(self, offering_id: int, *, lock=False) -> CourseOffering | None:
        row = self.sql.one(
            f"SELECT {_OFFERING_COLUMNS} FROM course_offerings AS o WHERE o.offering_id = %s {('FOR UPDATE' if lock else '')}",
            offering_id,
        )
        return _offering(row) if row else None

    def offering_summary(self, offering_id: int) -> dict[str, Any] | None:
        """Offering row + course code + lead membership id (Offering response)."""
        return self.sql.one(f"{_OFFERING_SUMMARY_SELECT} WHERE o.offering_id = %s", offering_id)

    def list_offerings(
        self, *, member_id: int | None, offset: int, limit: int
    ) -> tuple[list[dict[str, Any]], int]:
        """Classes where member_id is an active member; every class when member_id is None."""
        if member_id is None:
            where, params = "1 = 1", []
        else:
            where = """EXISTS (SELECT 1 FROM course_memberships AS me
                               WHERE me.offering_id = o.offering_id AND me.user_id = %s
                                 AND me.status = 'ACTIVE' AND (o.state <> 'DRAFT' OR me.course_role <> 'STUDENT'))"""
            params = [member_id]
        total = self.sql.scalar(
            f"SELECT COUNT(*) FROM course_offerings AS o WHERE {where}", *params
        )
        rows = self.sql.all(
            f"""{_OFFERING_SUMMARY_SELECT} WHERE {where}
                ORDER BY o.semester DESC, c.course_code, o.section_code
                LIMIT %s, %s""",
            *params,
            offset,
            limit,
        )
        return rows, total

    # ------------------------------------------------------------- memberships
    def find_membership(self, offering_id: int, user_id: int) -> CourseMembership | None:
        row = self.sql.one(
            f"""SELECT {_MEMBERSHIP_COLUMNS} FROM course_memberships AS m
                WHERE m.offering_id = %s AND m.user_id = %s""",
            offering_id,
            user_id,
        )
        return _membership(row) if row else None

    def is_in_course(self, *, course_id: int, user_id: int) -> bool:
        """Active member of any class of the course."""
        return bool(
            self.sql.scalar(
                """SELECT COUNT(*) FROM course_memberships AS m
                   JOIN course_offerings AS o ON o.offering_id = m.offering_id
                   WHERE o.course_id = %s AND m.user_id = %s AND m.status = 'ACTIVE'""",
                course_id,
                user_id,
            )
        )

    def list_memberships(
        self, offering_id: int, *, offset: int, limit: int
    ) -> tuple[list[dict[str, Any]], int]:
        """Active roster: professor first, then students by name."""
        total = self.sql.scalar(
            """SELECT COUNT(*) FROM course_memberships
               WHERE offering_id = %s AND status = 'ACTIVE'""",
            offering_id,
        )
        rows = self.sql.all(
            f"""SELECT {_MEMBERSHIP_COLUMNS}, u.full_name, u.status AS account_status,
                       u.role AS account_role, u.must_change_pwd
                FROM course_memberships AS m
                JOIN users AS u ON u.user_id = m.user_id
                WHERE m.offering_id = %s AND m.status = 'ACTIVE'
                ORDER BY CASE m.course_role WHEN 'STUDENT' THEN 1 ELSE 0 END,
                         u.full_name, m.membership_id
                LIMIT %s, %s""",
            offering_id,
            offset,
            limit,
        )
        return rows, total

    def insert_membership(
        self, *, offering_id: int, user_id: int, course_role: CourseRole
    ) -> CourseMembership:
        inserted_id = self.sql.insert(
            """INSERT INTO course_memberships (offering_id, user_id, course_role)

               VALUES (%s, %s, %s)""",
            offering_id,
            user_id,
            str(course_role),
        )
        row = self.sql.one(
            """SELECT membership_id, offering_id, user_id,
                      course_role, status, joined_at,
                      version FROM course_memberships WHERE membership_id = %s""",
            inserted_id,
        )
        return _membership(row)


_COURSE_COLUMNS = "c.course_code, c.course_name, c.credits, c.description"
_STUDENT_COLUMNS = "u.user_id, u.full_name, u.email, s.student_code"
_REGISTRATION_COLUMNS = """r.registration_id, r.course_id, r.student_id, r.status,
    r.requested_at, r.decided_by, r.decided_at"""
_REGISTRATION_FROM = """FROM course_registrations AS r
    JOIN courses AS c ON c.course_id = r.course_id
    JOIN users AS u ON u.user_id = r.student_id
    JOIN students AS s ON s.user_id = r.student_id"""
_OFFERING_COLUMNS = """o.offering_id, o.course_id, o.semester, o.section_code, o.title,
    o.state, o.version"""
_OFFERING_SUMMARY_SELECT = f"""SELECT {_OFFERING_COLUMNS}, c.course_code,
        lead_member.membership_id AS lead_membership_id
    FROM course_offerings AS o
    JOIN courses AS c ON c.course_id = o.course_id
    LEFT JOIN course_memberships AS lead_member
        ON lead_member.offering_id = o.offering_id AND lead_member.course_role = 'PRIMARY_INSTRUCTOR'
       AND lead_member.status = 'ACTIVE'"""
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
