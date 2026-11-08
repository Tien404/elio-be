"""SubmissionService from the class diagram: submission boxes (assignments) and submissions.

An Assignment is only a box (title, due date, max score) inside a topic; professors post the
instructions as a Material. Students upload 1-5 files (20 MB each) with POST /files
(purpose=SUBMISSION) and then confirm them. Every confirm is a new version; the newest one
counts and is marked late when made after the due date (the database clock decides).
"""

import hashlib
import secrets
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, BinaryIO

from app.core.errors import (
    ApiError,
    FeatureNotImplemented,
    not_found,
    version_conflict,
)
from app.domain.context import Actor
from app.domain.entities import PublishStatus
from app.infrastructure.db.repositories.assessment_repository import (
    AssessmentRepository,
    assignment_from_row,
)
from app.infrastructure.db.repositories.audit_repository import AuditRepository
from app.infrastructure.db.repositories.content_repository import ContentRepository
from app.infrastructure.db.repositories.course_repository import CourseRepository
from app.infrastructure.db.sql import Sql
from app.infrastructure.file_storage import FileStorage
from app.services.access import is_teacher, require_member, require_student, require_teacher
from app.services.content_service import stage_file

MAX_SUBMISSION_BYTES = 20_000_000  # report: submission files up to 20 MB each (decimal)
MAX_SUBMISSION_FILES = 5


def assignment_view(row: dict[str, Any]) -> dict[str, Any]:
    """Assignment response shape (OpenAPI contract); cutoffAt is null = no hard cutoff."""
    return {
        "id": row["activity_id"],
        "offeringId": row["offering_id"],
        "topicId": row["topic_id"],
        "title": row["title"],
        "instructions": row["instructions"] or None,
        "mode": "INDIVIDUAL",
        "status": row["status"],
        "openAt": row["open_at"],
        "dueAt": row["due_at"],
        "cutoffAt": None,
        "maxScore": float(row["max_score"]),
        "weight": 0,
        "version": row["version"],
    }


def submission_view(row: dict[str, Any]) -> dict[str, Any]:
    """Submission response shape (OpenAPI contract); currentVersion is the one that counts."""
    current = None
    if row["version_no"]:
        current = {
            "submissionId": row["submission_id"],
            "versionNo": row["version_no"],
            "fileIds": [int(x) for x in (row["file_ids"] or "").split(",") if x],
            "submittedByStudentId": row["submitted_by"],
            "submittedAt": row["submitted_at"],
            "isLate": bool(row["is_late"]),
            "receiptCode": row["receipt_code"],
        }
    return {
        "id": row["submission_id"],
        "assignmentId": row["assignment_id"],
        "subjectType": "STUDENT",
        "subjectId": row["student_id"],
        "recipientStudentIds": [row["student_id"]],
        "currentVersion": current,
        "version": row["version"],
        "status": row["status"],
    }


def check_submission_file_access(sql: Sql, actor: Actor, file: dict[str, Any]) -> None:
    """downloadSubmissionFile: the student who uploaded it, or the class professor."""
    if file["uploaded_by"] == actor.user_id:
        return
    membership = CourseRepository(sql).find_membership(file["offering_id"], actor.user_id)
    if membership is None or not membership.is_active() or not is_teacher(membership):
        raise not_found("File")


def _page(items: list, page: int, page_size: int, total: int) -> dict[str, Any]:
    return {
        "items": items,
        "page": page,
        "pageSize": page_size,
        "totalItems": total,
        "totalPages": (total + page_size - 1) // page_size,
    }


class SubmissionService:
    def __init__(self, database=None, storage: FileStorage | None = None):
        self.database = database
        self.storage = storage

    # -------------------------------------------------------- submission boxes
    def save_assignment(
        self,
        *,
        actor: Actor,
        offering_id: int,
        topic_id: int,
        title: str,
        due_at: datetime,
        max_score: Decimal,
        status: str,
        instructions: str | None = None,
    ) -> dict[str, Any]:
        """The class professor adds a submission box to a topic."""
        title = title.strip()
        if not title:
            raise ApiError(400, "INVALID_REQUEST", "Title must not be blank.")
        with self.database.transaction() as connection:
            sql = Sql(connection)
            require_teacher(CourseRepository(sql), actor, offering_id)
            topic = ContentRepository(sql).get_topic(topic_id)
            if topic is None or topic.offering_id != offering_id:
                raise ApiError(422, "TOPIC_NOT_FOUND", "The topic is not in this class.")
            repo = AssessmentRepository(sql)
            if _aware(due_at) <= repo.db_now():
                raise ApiError(400, "INVALID_REQUEST", "The due date must be in the future.")
            assignment_id = repo.insert_assignment(
                offering_id=offering_id,
                topic_id=topic_id,
                title=title,
                instructions=(instructions or "").strip() or None,
                due_at=_aware(due_at),
                max_score=max_score,
                status=PublishStatus(status),
            )
            AuditRepository(sql).record(
                actor_id=actor.user_id,
                action="ASSIGNMENT_CREATED",
                target_type="ASSIGNMENT",
                target_id=assignment_id,
                details={"status": status},
            )
            row = repo.get_assignment(assignment_id)
        return assignment_view(row)

    def list_assignments(
        self, *, actor: Actor, offering_id: int, page: int, page_size: int
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            sql = Sql(connection)
            member = require_member(CourseRepository(sql), actor, offering_id)
            rows, total = AssessmentRepository(sql).list_assignments(
                offering_id,
                published_only=not is_teacher(member),
                offset=(page - 1) * page_size,
                limit=page_size,
            )
        return _page([assignment_view(r) for r in rows], page, page_size, total)

    def get_assignment(self, *, actor: Actor, assignment_id: int) -> dict[str, Any]:
        with self.database.transaction() as connection:
            sql = Sql(connection)
            row, _ = self._visible_assignment(sql, actor, assignment_id)
        return assignment_view(row)

    def update_assignment(
        self,
        *,
        actor: Actor,
        assignment_id: int,
        expected_version: int,
        title: str | None,
        due_at: datetime | None,
        status: str | None,
    ) -> dict[str, Any]:
        """Rename, move the due date, or publish (publishAssignment). Needs the version."""
        with self.database.transaction() as connection:
            sql = Sql(connection)
            repo = AssessmentRepository(sql)
            row = repo.get_assignment(assignment_id, lock=True)
            if row is None:
                raise not_found("Assignment")
            require_teacher(CourseRepository(sql), actor, row["offering_id"])
            if row["version"] != expected_version:
                raise version_conflict(row["version"])
            assignment = assignment_from_row(row)
            if title is not None:
                if not title.strip():
                    raise ApiError(400, "INVALID_REQUEST", "Title must not be blank.")
                assignment.title = title.strip()
            if due_at is not None:
                if _aware(due_at) < row["open_at"]:
                    raise ApiError(400, "INVALID_REQUEST", "The due date is before opening.")
                assignment.due_at = _aware(due_at)
            if status == PublishStatus.PUBLISHED:
                assignment.publish()
            elif status is not None:
                assignment.status = PublishStatus(status)
            repo.update_assignment(assignment)
            row = repo.get_assignment(assignment_id)
        return assignment_view(row)

    # ------------------------------------------------------------- submissions
    def prepare_file(
        self,
        *,
        actor: Actor,
        offering_id: int,
        assignment_id: int | None,
        file_name: str | None,
        content_type: str | None,
        stream: BinaryIO,
    ) -> dict[str, Any]:
        """uploadFiles: a class student stores one file for an open submission box."""
        if assignment_id is None:
            raise ApiError(400, "INVALID_REQUEST", "assignmentId is required for SUBMISSION.")
        return stage_file(
            self.database,
            self.storage,
            check=self._can_submit_to(actor, offering_id, assignment_id),
            actor=actor,
            offering_id=offering_id,
            purpose="SUBMISSION",
            assignment_id=assignment_id,
            file_name=file_name,
            content_type=content_type,
            stream=stream,
            max_bytes=MAX_SUBMISSION_BYTES,
            limit_text="Submission files can be at most 20 MB each.",
        )

    def confirm_submission(
        self, *, actor: Actor, assignment_id: int, expected_version: int, file_ids: list[int]
    ) -> dict[str, Any]:
        """Turn uploaded files into a new submission version (the newest one counts)."""
        if not 1 <= len(file_ids) <= MAX_SUBMISSION_FILES or len(set(file_ids)) != len(file_ids):
            raise ApiError(400, "INVALID_REQUEST", "Submit 1 to 5 different files.")
        with self.database.transaction() as connection:
            sql = Sql(connection)
            repo = AssessmentRepository(sql)
            row = repo.get_assignment(assignment_id)
            if row is None:
                raise not_found("Assignment")
            self._can_submit_to(actor, row["offering_id"], assignment_id)(sql)
            assignment = assignment_from_row(row)

            stream = repo.lock_submission(assignment_id=assignment_id, student_id=actor.user_id)
            current = stream["version"] if stream else 0
            if expected_version != current:
                raise version_conflict(current)

            files = ContentRepository(sql)
            hashes = []
            for file_id in file_ids:
                file = files.get_file(file_id, lock=True)
                _check_own_staged_file(file, actor, assignment_id)
                hashes.append(f"{file_id}:{file['sha256']}")

            submission_id = (
                stream["submission_id"]
                if stream
                else repo.insert_submission(assignment_id=assignment_id, student_id=actor.user_id)
            )
            now = repo.db_now()
            repo.insert_version(
                submission_id=submission_id,
                version_no=current + 1,
                submitted_by=actor.user_id,
                submitted_at=now,
                is_late=assignment.is_late(now),
                receipt_code="R-" + secrets.token_hex(8).upper(),
                request_key=secrets.token_hex(16),
                request_hash=hashlib.sha256("|".join(hashes).encode()).hexdigest(),
                file_ids=file_ids,
            )
            for file_id in file_ids:
                files.attach_file(file_id)
            AuditRepository(sql).record(
                actor_id=actor.user_id,
                action="SUBMISSION_CONFIRMED",
                target_type="SUBMISSION",
                target_id=submission_id,
                details={"versionNo": current + 1, "files": len(file_ids)},
            )
            view = repo.get_submission(submission_id)
        return submission_view(view)

    def get_my_submission(self, *, actor: Actor, assignment_id: int) -> dict[str, Any]:
        with self.database.transaction() as connection:
            sql = Sql(connection)
            self._visible_assignment(sql, actor, assignment_id)
            row = AssessmentRepository(sql).find_submission(
                assignment_id=assignment_id, student_id=actor.user_id
            )
        if row is None:
            raise ApiError(404, "NOT_SUBMITTED", "You have not submitted anything yet.")
        return submission_view(row)

    def list_submissions(
        self, *, actor: Actor, assignment_id: int, page: int, page_size: int
    ) -> dict[str, Any]:
        """The class professor's list of submitted work, oldest first."""
        with self.database.transaction() as connection:
            sql = Sql(connection)
            repo = AssessmentRepository(sql)
            row = repo.get_assignment(assignment_id)
            if row is None:
                raise not_found("Assignment")
            require_teacher(CourseRepository(sql), actor, row["offering_id"])
            rows, total = repo.list_submissions(
                assignment_id, offset=(page - 1) * page_size, limit=page_size
            )
        return _page([submission_view(r) for r in rows], page, page_size, total)

    def get_submission(self, *, actor: Actor, submission_id: int) -> dict[str, Any]:
        """The student who owns it, or the class professor."""
        with self.database.transaction() as connection:
            sql = Sql(connection)
            repo = AssessmentRepository(sql)
            row = repo.get_submission(submission_id)
            if row is None:
                raise not_found("Submission")
            if row["student_id"] != actor.user_id:
                assignment = repo.get_assignment(row["assignment_id"])
                membership = CourseRepository(sql).find_membership(
                    assignment["offering_id"], actor.user_id
                )
                if membership is None or not membership.is_active() or not is_teacher(membership):
                    raise not_found("Submission")
        return submission_view(row)

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _visible_assignment(sql: Sql, actor: Actor, assignment_id: int):
        """Members see published boxes; the professor also sees drafts."""
        row = AssessmentRepository(sql).get_assignment(assignment_id)
        if row is None:
            raise not_found("Assignment")
        member = require_member(CourseRepository(sql), actor, row["offering_id"])
        if not is_teacher(member) and row["status"] != PublishStatus.PUBLISHED:
            raise not_found("Assignment")
        return row, member

    @staticmethod
    def _can_submit_to(actor: Actor, offering_id: int, assignment_id: int) -> Callable[[Sql], None]:
        """Check used before upload and on confirm: class student + open box of that class."""

        def check(sql: Sql) -> None:
            require_student(CourseRepository(sql), actor, offering_id)
            row = AssessmentRepository(sql).get_assignment(assignment_id)
            if row is None or row["offering_id"] != offering_id:
                raise not_found("Assignment")
            if not assignment_from_row(row).is_open():
                raise not_found("Assignment")

        return check

    # ------------------------------------------- placeholders behind 501 routes
    def create_group(self, **kwargs: object):
        raise FeatureNotImplemented("SubmissionService.create_group")

    def get_group(self, **kwargs: object):
        raise FeatureNotImplemented("SubmissionService.get_group")

    def get_submission_receipt(self, **kwargs: object):
        raise FeatureNotImplemented("SubmissionService.get_submission_receipt")

    def list_groups(self, **kwargs: object):
        raise FeatureNotImplemented("SubmissionService.list_groups")

    def update_group(self, **kwargs: object):
        raise FeatureNotImplemented("SubmissionService.update_group")


def _aware(value: datetime) -> datetime:
    """Treat a date without a time zone as UTC."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _check_own_staged_file(file: dict[str, Any] | None, actor: Actor, assignment_id: int) -> None:
    if (
        file is None
        or file["purpose"] != "SUBMISSION"
        or file["assignment_id"] != assignment_id
        or file["uploaded_by"] != actor.user_id
        or file["state"] != "STAGING"
    ):
        raise ApiError(422, "FILE_NOT_USABLE", "Upload each file to this assignment first.")
    if file["expires_at"] <= datetime.now(UTC):
        raise ApiError(422, "FILE_NOT_USABLE", "An upload expired; upload it again.")
