"""T-SQL for assignments (submission boxes) and individual submissions. Never commits."""

from datetime import UTC, datetime
from typing import Any

from app.domain.entities import Assignment, PublishStatus
from app.infrastructure.db.sql import Sql

_ASSIGNMENT_SELECT = """SELECT a.activity_id, a.offering_id, a.topic_id, a.title, a.max_score,
        a.status, a.version, a.weight_pct, a.is_mandatory, x.instructions, x.open_at, x.due_at, x.cutoff_at
    FROM dbo.activities AS a
    JOIN dbo.assignments AS x ON x.activity_id = a.activity_id"""

_SUBMISSION_SELECT = """SELECT s.submission_id, s.assignment_id, s.student_id, s.status,
        s.version, v.version_no, v.submitted_by, v.submitted_at, v.is_late, v.receipt_code,
        (SELECT STRING_AGG(CAST(sf.file_id AS VARCHAR(12)), ',')
                WITHIN GROUP (ORDER BY sf.file_no)
         FROM dbo.submission_files AS sf
         WHERE sf.submission_id = s.submission_id AND sf.version_no = s.version) AS file_ids
    FROM dbo.submissions AS s
    LEFT JOIN dbo.submission_versions AS v
        ON v.submission_id = s.submission_id AND v.version_no = s.version"""


def _utc(value: datetime) -> str:
    """Send instants as UTC ISO text; SQL casts them to DATETIMEOFFSET."""
    return value.astimezone(UTC).isoformat()


class AssessmentRepository:
    def __init__(self, sql: Sql):
        self.sql = sql

    def db_now(self) -> datetime:
        """The database clock (UTC) decides deadlines, not the API server's clock."""
        return self.sql.scalar("SELECT CAST(SYSUTCDATETIME() AS DATETIMEOFFSET(7))")

    # ------------------------------------------------------------- assignments
    def insert_assignment(self, *, offering_id, data) -> int:
        activity_id = self.sql.scalar(
            """INSERT dbo.activities (offering_id, topic_id, activity_type, title, max_score,
                   weight_pct, is_mandatory, status)
               OUTPUT INSERTED.activity_id VALUES (?, ?, 'ASSIGNMENT', ?, ?, ?, ?, ?)""",
            offering_id,
            data["topicId"],
            data["title"],
            data["maxScore"],
            data["weight"],
            data["mandatory"],
            data["status"],
        )
        self.sql.execute(
            """INSERT dbo.assignments (activity_id, instructions, open_at, due_at, cutoff_at)
               VALUES (?, ?, CAST(? AS DATETIMEOFFSET(7)), CAST(? AS DATETIMEOFFSET(7)),
                       CAST(? AS DATETIMEOFFSET(7)))""",
            activity_id,
            data["instructions"] or "",
            _utc(data["openAt"]),
            _utc(data["dueAt"]),
            _utc(data["cutoffAt"]),
        )
        return activity_id

    def get_assignment(self, assignment_id: int, *, lock: bool = False) -> dict[str, Any] | None:
        if lock:
            self.sql.execute(
                "SELECT 1 FROM dbo.activities WITH (UPDLOCK, ROWLOCK) WHERE activity_id = ?",
                assignment_id,
            )
        return self.sql.one(
            f"{_ASSIGNMENT_SELECT} WHERE a.activity_id = ? AND a.activity_type = 'ASSIGNMENT'",
            assignment_id,
        )

    def list_assignments(
        self, offering_id: int, *, published_only: bool, offset: int, limit: int
    ) -> tuple[list[dict[str, Any]], int]:
        where = "a.offering_id = ? AND a.activity_type = 'ASSIGNMENT'"
        if published_only:
            where += " AND a.status = 'PUBLISHED'"
        total = self.sql.scalar(
            f"SELECT COUNT(*) FROM dbo.activities AS a WHERE {where}", offering_id
        )
        rows = self.sql.all(
            f"""{_ASSIGNMENT_SELECT} WHERE {where}
                ORDER BY x.due_at, a.activity_id OFFSET ? ROWS FETCH NEXT ? ROWS ONLY""",
            offering_id,
            offset,
            limit,
        )
        return rows, total

    def update_assignment(self, assignment_id, data):
        self.sql.execute(
            """UPDATE dbo.activities SET title=?, topic_id=?, max_score=?, weight_pct=?,
                   is_mandatory=?, status=?, version=version+1 WHERE activity_id=?""",
            data["title"],
            data["topicId"],
            data["maxScore"],
            data["weight"],
            data["mandatory"],
            data["status"],
            assignment_id,
        )
        self.sql.execute(
            """UPDATE dbo.assignments SET instructions=?, open_at=CAST(? AS DATETIMEOFFSET(7)),
                   due_at=CAST(? AS DATETIMEOFFSET(7)), cutoff_at=CAST(? AS DATETIMEOFFSET(7))
               WHERE activity_id=?""",
            data["instructions"] or "",
            _utc(data["openAt"]),
            _utc(data["dueAt"]),
            _utc(data["cutoffAt"]),
            assignment_id,
        )

    def attachment_ids(self, assignment_id):
        return [
            r["file_id"]
            for r in self.sql.all(
                "SELECT file_id FROM dbo.assignment_attachments WHERE assignment_id=? ORDER BY attachment_no",
                assignment_id,
            )
        ]

    def set_attachments(self, assignment_id, file_ids):
        self.sql.execute("DELETE dbo.assignment_attachments WHERE assignment_id=?", assignment_id)
        for number, file_id in enumerate(file_ids, 1):
            self.sql.execute(
                "INSERT dbo.assignment_attachments (assignment_id, attachment_no, file_id) VALUES (?, ?, ?)",
                assignment_id,
                number,
                file_id,
            )

    def has_grade(self, assignment_id):
        return bool(
            self.sql.scalar(
                """SELECT COUNT(*) FROM dbo.grades AS g JOIN dbo.submissions AS s
               ON s.submission_id=g.submission_id WHERE s.assignment_id=?""",
                assignment_id,
            )
        )

    # ------------------------------------------------------------- submissions
    def lock_submission(self, *, assignment_id: int, student_id: int) -> dict[str, Any] | None:
        """The student's submission stream, locked (key-range too, so a first submit
        from two tabs cannot create two rows)."""
        return self.sql.one(
            """SELECT submission_id, status, version
               FROM dbo.submissions WITH (UPDLOCK, HOLDLOCK)
               WHERE assignment_id = ? AND student_id = ?""",
            assignment_id,
            student_id,
        )

    def insert_submission(self, *, assignment_id: int, student_id: int) -> int:
        return self.sql.scalar(
            """INSERT dbo.submissions (assignment_id, owner_type, student_id)
               OUTPUT INSERTED.submission_id VALUES (?, 'INDIVIDUAL', ?)""",
            assignment_id,
            student_id,
        )

    def insert_version(
        self,
        *,
        submission_id: int,
        version_no: int,
        submitted_by: int,
        submitted_at: datetime,
        is_late: bool,
        receipt_code: str,
        request_key: str,
        request_hash: str,
        file_ids: list[int],
    ) -> None:
        self.sql.execute(
            """INSERT dbo.submission_versions (submission_id, version_no, submitted_by,
                   submitted_at, is_late, receipt_code, request_key, request_hash)
               VALUES (?, ?, ?, CAST(? AS DATETIMEOFFSET(7)), ?, ?, ?, ?)""",
            submission_id,
            version_no,
            submitted_by,
            _utc(submitted_at),
            is_late,
            receipt_code,
            request_key,
            request_hash,
        )
        for file_no, file_id in enumerate(file_ids, start=1):
            self.sql.execute(
                """INSERT dbo.submission_files (submission_id, version_no, file_no, file_id)
                   VALUES (?, ?, ?, ?)""",
                submission_id,
                version_no,
                file_no,
                file_id,
            )
        self.sql.execute(
            "UPDATE dbo.submissions SET status = 'SUBMITTED', version = ? WHERE submission_id = ?",
            version_no,
            submission_id,
        )

    def get_submission(self, submission_id: int) -> dict[str, Any] | None:
        return self.sql.one(f"{_SUBMISSION_SELECT} WHERE s.submission_id = ?", submission_id)

    def find_submission(self, *, assignment_id: int, student_id: int) -> dict[str, Any] | None:
        return self.sql.one(
            f"{_SUBMISSION_SELECT} WHERE s.assignment_id = ? AND s.student_id = ?",
            assignment_id,
            student_id,
        )

    def list_submissions(
        self, assignment_id: int, *, offset: int, limit: int
    ) -> tuple[list[dict[str, Any]], int]:
        total = self.sql.scalar(
            "SELECT COUNT(*) FROM dbo.submissions WHERE assignment_id = ? AND status = 'SUBMITTED'",
            assignment_id,
        )
        rows = self.sql.all(
            f"""{_SUBMISSION_SELECT} WHERE s.assignment_id = ? AND s.status = 'SUBMITTED'
                ORDER BY v.submitted_at, s.submission_id OFFSET ? ROWS FETCH NEXT ? ROWS ONLY""",
            assignment_id,
            offset,
            limit,
        )
        return rows, total


def assignment_from_row(row: dict[str, Any]) -> Assignment:
    return Assignment(
        assignment_id=row["activity_id"],
        offering_id=row["offering_id"],
        topic_id=row["topic_id"],
        title=row["title"],
        due_at=row["due_at"],
        max_score=row["max_score"],
        status=PublishStatus(row["status"]),
        instructions=row["instructions"] or None,
        version=row["version"],
        open_at=row["open_at"],
        cutoff_at=row["cutoff_at"],
    )
