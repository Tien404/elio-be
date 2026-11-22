"MySQL SQL for grades and grade revisions. Never commits."

from decimal import Decimal
from typing import Any

from app.infrastructure.db.sql import Sql

# One row per assignment of the class, with this student's submission, the current
# draft revision and the released (published) revision.
_REPORT_SELECT = """SELECT a.activity_id, a.title, a.max_score, a.weight_pct, x.due_at,
        s.submission_id, s.group_id, s.status AS submission_status,
        g.grade_id, g.draft_revision_no, g.published_revision_no, g.published_at,
        dr.score AS draft_score, dr.special_mark AS draft_mark, dr.feedback AS draft_feedback,
        pr.score AS released_score, pr.special_mark AS released_mark,
        pr.feedback AS released_feedback
    FROM activities AS a
    JOIN assignments AS x ON x.activity_id = a.activity_id
    LEFT JOIN (SELECT r.submission_id,r.student_id,sx.assignment_id FROM submission_roster r JOIN submissions sx ON sx.submission_id=r.submission_id) AS gm ON gm.assignment_id=a.activity_id AND gm.student_id = %s
    LEFT JOIN submissions AS s ON s.assignment_id = a.activity_id
        AND (s.student_id = %s OR s.submission_id = gm.submission_id)
    LEFT JOIN grades AS g ON g.submission_id = s.submission_id
    LEFT JOIN grade_revisions AS dr
        ON dr.grade_id = g.grade_id AND dr.revision_no = g.draft_revision_no
    LEFT JOIN grade_revisions AS pr
        ON pr.grade_id = g.grade_id AND pr.revision_no = g.published_revision_no
    WHERE a.offering_id = %s AND a.activity_type = 'ASSIGNMENT'
      AND a.status IN ('PUBLISHED', 'ARCHIVED')"""


class GradingRepository:
    def __init__(self, sql: Sql):
        self.sql = sql

    # ------------------------------------------------------------ grade report
    def report_rows(
        self, offering_id: int, student_id: int, *, assignment_id: int | None = None
    ) -> list[dict[str, Any]]:
        if assignment_id is None:
            return self.sql.all(
                f"{_REPORT_SELECT} ORDER BY x.due_at, a.activity_id",
                student_id,
                student_id,
                offering_id,
            )
        return self.sql.all(
            f"{_REPORT_SELECT} AND a.activity_id = %s",
            student_id,
            student_id,
            offering_id,
            assignment_id,
        )

    def find_student(self, offering_id: int, student_id: int) -> dict[str, Any] | None:
        """An active student of the class."""
        return self.sql.one(
            """SELECT u.user_id, u.full_name, st.student_code
               FROM course_memberships AS m
               JOIN users AS u ON u.user_id = m.user_id
               JOIN students AS st ON st.user_id = m.user_id
               WHERE m.offering_id = %s AND m.user_id = %s
                 AND m.status = 'ACTIVE' AND m.course_role = 'STUDENT'""",
            offering_id,
            student_id,
        )

    def class_students(self, offering_id: int) -> list[dict[str, Any]]:
        """Active students of the class, by name."""
        return self.sql.all(
            """SELECT u.user_id, u.full_name, st.student_code
               FROM course_memberships AS m
               JOIN users AS u ON u.user_id = m.user_id
               JOIN students AS st ON st.user_id = m.user_id
               WHERE m.offering_id = %s AND m.status = 'ACTIVE' AND m.course_role = 'STUDENT'
               ORDER BY u.full_name, u.user_id""",
            offering_id,
        )

    def my_class_ids(self, student_id: int) -> list[int]:
        """Classes the student is in (draft classes are hidden from students)."""
        return [
            r["offering_id"]
            for r in self.sql.all(
                """SELECT o.offering_id FROM course_memberships AS m
                   JOIN course_offerings AS o ON o.offering_id = m.offering_id
                   WHERE m.user_id = %s AND m.status = 'ACTIVE'
                     AND m.course_role = 'STUDENT' AND o.state <> 'DRAFT'
                   ORDER BY o.semester DESC, o.offering_id""",
                student_id,
            )
        ]

    # ------------------------------------------------------------ saving grades
    def lock_grade(self, submission_id: int) -> dict[str, Any] | None:
        return self.sql.one(
            "SELECT grade_id, draft_revision_no, published_revision_no, version FROM grades WHERE submission_id = %s FOR UPDATE",
            submission_id,
        )

    def insert_grade(self, submission_id: int) -> int:
        return self.sql.insert("INSERT INTO grades (submission_id) VALUES (%s)", submission_id)

    def add_revision(
        self,
        *,
        grade_id: int,
        submission_id: int,
        source_version_no: int | None,
        score: Decimal,
        special_mark: str | None,
        feedback: str | None,
        revised_by: int,
        reason: str | None = None,
        zero_reason: str | None = None,
    ) -> int:
        """Store a new revision and make it the draft. Returns its number."""
        number = (
            self.sql.scalar(
                "SELECT COALESCE(MAX(revision_no), 0) FROM grade_revisions WHERE grade_id = %s",
                grade_id,
            )
            + 1
        )
        missing = source_version_no is None  # no submitted work: a "missing work" zero
        self.sql.execute(
            """INSERT INTO grade_revisions (grade_id, revision_no, submission_id,
                   source_version_no, score, special_mark, feedback, is_missing_zero,
                   zero_reason, revised_by, reason)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            grade_id,
            number,
            submission_id,
            source_version_no,
            score,
            special_mark,
            feedback,
            missing,
            zero_reason if missing else None,
            revised_by,
            reason,
        )
        self.sql.execute(
            "UPDATE grades SET draft_revision_no = %s, version = version + 1 WHERE grade_id = %s",
            number,
            grade_id,
        )
        return number

    def unreleased_students(self, assignment_id: int) -> list[int]:
        """Students with a saved grade that is not visible to them yet."""
        return [
            r["student_id"]
            for r in self.sql.all(
                """SELECT COALESCE(s.student_id, m.student_id) AS student_id
                   FROM grades AS g
                   JOIN submissions AS s ON s.submission_id = g.submission_id
                   LEFT JOIN group_members AS m ON m.group_id = s.group_id
                   WHERE s.assignment_id = %s AND g.draft_revision_no IS NOT NULL
                     AND (g.published_revision_no IS NULL
                          OR g.published_revision_no <> g.draft_revision_no)""",
                assignment_id,
            )
        ]

    def get_grade(self, grade_id: int) -> dict[str, Any] | None:
        return self.sql.one(
            """SELECT g.grade_id, g.submission_id, g.draft_revision_no, g.published_revision_no,
                      g.published_at, g.version, s.assignment_id, a.offering_id, a.title
               FROM grades AS g
               JOIN submissions AS s ON s.submission_id = g.submission_id
               JOIN activities AS a ON a.activity_id = s.assignment_id
               WHERE g.grade_id = %s""",
            grade_id,
        )

    def revisions(self, grade_id: int) -> list[dict[str, Any]]:
        """Every saved version of the grade, newest first (the edit history)."""
        return self.sql.all(
            """SELECT r.revision_no, r.score, r.special_mark, r.feedback, r.revised_at, r.source_version_no, r.reason, r.zero_reason, r.is_missing_zero,
                      r.revised_by, u.full_name AS revised_by_name
               FROM grade_revisions AS r JOIN users AS u ON u.user_id = r.revised_by
               WHERE r.grade_id = %s ORDER BY r.revision_no DESC""",
            grade_id,
        )

    def release_one(self, grade_id: int) -> int:
        """Make this one grade's draft visible. Returns 1 if it changed."""
        return self.sql.execute(
            """UPDATE grades SET published_revision_no = draft_revision_no,
                   published_at = UTC_TIMESTAMP(6), version = version + 1
               WHERE grade_id = %s AND draft_revision_no IS NOT NULL
                 AND (published_revision_no IS NULL OR published_revision_no <> draft_revision_no)""",
            grade_id,
        )

    def release(self, assignment_id: int) -> int:
        """Make every saved draft of the assignment visible. Returns how many changed."""
        return self.sql.execute(
            """UPDATE grades AS g
               JOIN submissions AS s ON s.submission_id = g.submission_id
               SET g.published_revision_no = g.draft_revision_no,
                   g.published_at = UTC_TIMESTAMP(6),
                   g.version = g.version + 1
               WHERE s.assignment_id = %s AND g.draft_revision_no IS NOT NULL
                 AND (g.published_revision_no IS NULL
                      OR g.published_revision_no <> g.draft_revision_no)""",
            assignment_id,
        )
