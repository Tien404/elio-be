import hashlib
import secrets
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, BinaryIO

from app.api.schemas.common import utc_payload
from app.core.errors import (
    ApiError,
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
from app.infrastructure.db.repositories.group_repository import GroupRepository
from app.infrastructure.db.sql import Sql
from app.infrastructure.file_storage import FileStorage
from app.services.access import is_teacher, require_member, require_student, require_teacher
from app.services.content_service import stage_file
from app.services.notification_service import notify_course

MAX_SUBMISSION_BYTES = 20_000_000  # report: submission files up to 20 MB each (decimal)
MAX_SUBMISSION_FILES = 5


def assignment_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["activity_id"],
        "offeringId": row["offering_id"],
        "topicId": row["topic_id"],
        "title": row["title"],
        "instructions": row["instructions"] or None,
        "mode": "GROUP" if row["is_group_work"] else "INDIVIDUAL",
        "maxGroupSize": row["max_group_size"],
        "groupFormation": row["group_formation"],
        "status": row["status"],
        "openAt": row["open_at"],
        "dueAt": row["due_at"],
        "cutoffAt": row["cutoff_at"],
        "maxScore": float(row["max_score"]),
        "weight": float(row["weight_pct"]),
        "version": row["version"],
        "mandatory": bool(row["is_mandatory"]),
    }


def submission_view(row: dict[str, Any], members: list[int] | None = None) -> dict[str, Any]:
    """Submission response shape (OpenAPI contract); currentVersion is the one that counts.
    Group submissions: subject = the group, recipients = its members."""
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
        "subjectType": "GROUP" if row["group_id"] else "STUDENT",
        "subjectId": row["group_id"] or row["student_id"],
        "recipientStudentIds": members if row["group_id"] else [row["student_id"]],
        "currentVersion": current,
        "version": row["version"],
        "status": row["status"],
    }


def check_submission_file_access(sql: Sql, actor: Actor, file: dict[str, Any]) -> None:
    """downloadSubmissionFile: the student who uploaded it, or the class professor."""
    require_member(CourseRepository(sql), actor, file["offering_id"])
    if file["uploaded_by"] == actor.user_id:
        return
    if file["state"] == "ATTACHED" and sql.scalar(
        """SELECT COUNT(*) FROM submission_files f
        JOIN submission_roster r ON r.submission_id=f.submission_id WHERE f.file_id=%s AND r.student_id=%s""",
        file["file_id"],
        actor.user_id,
    ):
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
    def _assignment_view(self, sql, row):
        repo = AssessmentRepository(sql)
        view = assignment_view(row)
        files = ContentRepository(sql)
        from app.services.content_service import file_view

        view["attachments"] = [
            file_view(files.get_file(i)) for i in repo.attachment_ids(row["activity_id"])
        ]
        view["serverNow"] = repo.db_now()
        return view

    def _validate_assignment(self, sql, actor, offering_id, data, assignment_id=None):
        if not data["title"].strip():
            raise ApiError(400, "INVALID_REQUEST", "Title must not be blank.")
        data["title"] = data["title"].strip()
        if not data["openAt"] <= data["dueAt"] <= data["cutoffAt"]:
            raise ApiError(400, "INVALID_SCHEDULE", "Opening must be before due date and cutoff.")
        if (data["mode"] == "GROUP") != (data.get("maxGroupSize") is not None):
            raise ApiError(
                400, "INVALID_REQUEST", "Group work needs maxGroupSize; individual work has none."
            )
        if data["topicId"] is not None:
            topic = ContentRepository(sql).get_topic(data["topicId"])
            if topic is None or topic.offering_id != offering_id:
                raise ApiError(422, "TOPIC_NOT_FOUND", "The topic is not in this class.")
        if len(data["fileIds"]) > 5 or len(set(data["fileIds"])) != len(data["fileIds"]):
            raise ApiError(400, "INVALID_REQUEST", "Choose at most five different attachments.")
        repo = AssessmentRepository(sql)
        old_ids = repo.attachment_ids(assignment_id) if assignment_id else []
        files = ContentRepository(sql)
        for file_id in data["fileIds"]:
            file = files.get_file(file_id, lock=True)
            if (
                file is None
                or file["offering_id"] != offering_id
                or file["purpose"] != "ASSIGNMENT_ATTACHMENT"
                or file["size_bytes"] > 20_000_000
            ):
                raise ApiError(422, "FILE_NOT_USABLE", "Invalid assignment attachment.")
            if file_id in old_ids and file["state"] == "ATTACHED":
                continue
            if (
                file["state"] != "STAGING"
                or file["uploaded_by"] != actor.user_id
                or file["expires_at"] <= repo.db_now()
            ):
                raise ApiError(
                    422, "FILE_NOT_USABLE", "Upload each attachment before attaching it."
                )

    def save_assignment(self, *, actor, offering_id, data):
        with self.database.transaction() as connection:
            sql = Sql(connection)
            require_teacher(CourseRepository(sql), actor, offering_id)
            self._validate_assignment(sql, actor, offering_id, data)
            repo = AssessmentRepository(sql)
            assignment_id = repo.insert_assignment(offering_id=offering_id, data=data)
            sql.execute(
                "UPDATE assignments SET group_formation=%s WHERE activity_id=%s",
                data.get("groupFormation", "SELF"),
                assignment_id,
            )
            repo.set_attachments(assignment_id, data["fileIds"])
            for file_id in data["fileIds"]:
                ContentRepository(sql).attach_file(file_id)
            AuditRepository(sql).record(
                actor_id=actor.user_id,
                action="ASSIGNMENT_CREATED",
                target_type="ASSIGNMENT",
                target_id=assignment_id,
                details={"status": data["status"]},
            )
            if data["status"] == "PUBLISHED":
                _notify_published(sql, actor, offering_id, assignment_id, data["title"])
            return self._assignment_view(sql, repo.get_assignment(assignment_id))

    def list_assignments(self, *, actor, offering_id, page, page_size):
        with self.database.transaction() as connection:
            sql = Sql(connection)
            member = require_member(CourseRepository(sql), actor, offering_id)
            rows, total = AssessmentRepository(sql).list_assignments(
                offering_id,
                published_only=not is_teacher(member),
                offset=(page - 1) * page_size,
                limit=page_size,
            )
            return _page([self._assignment_view(sql, r) for r in rows], page, page_size, total)

    def get_assignment(self, *, actor, assignment_id):
        with self.database.transaction() as connection:
            sql = Sql(connection)
            row, _ = self._visible_assignment(sql, actor, assignment_id)
            return self._assignment_view(sql, row)

    def update_assignment(self, *, actor, assignment_id, expected_version, changes):
        with self.database.transaction() as connection:
            sql = Sql(connection)
            repo = AssessmentRepository(sql)
            row = repo.get_assignment(assignment_id)
            if row is None:
                raise not_found("Assignment")
            require_teacher(CourseRepository(sql), actor, row["offering_id"])
            row = repo.get_assignment(assignment_id, lock=True)
            if row["version"] != expected_version:
                raise version_conflict(row["version"])
            old = assignment_view(row)
            if "groupFormation" in changes and changes["groupFormation"] != old["groupFormation"]:
                if sql.scalar(
                    "SELECT COUNT(*) FROM assignment_groups WHERE assignment_id=%s", assignment_id
                ):
                    raise ApiError(
                        409, "GROUPS_EXIST", "Group formation cannot change after groups exist."
                    )
            data = {
                k: old[k]
                for k in [
                    "title",
                    "topicId",
                    "instructions",
                    "mode",
                    "status",
                    "openAt",
                    "dueAt",
                    "cutoffAt",
                    "maxScore",
                    "weight",
                    "mandatory",
                    "maxGroupSize",
                ]
            }
            data["fileIds"] = repo.attachment_ids(assignment_id)
            if "instructions" in changes:
                changes["instructions"] = changes["instructions"] or None
            data.update(changes)
            if row["status"] == "ARCHIVED":
                raise ApiError(409, "ASSIGNMENT_READ_ONLY", "Archived assignments are read-only.")
            if row["status"] == "PUBLISHED":
                editable = {"dueAt", "cutoffAt", "status"}
                if any(
                    k not in editable
                    and (
                        Decimal(str(data[k])) != Decimal(str(old.get(k, data[k])))
                        if k in ("maxScore", "weight")
                        else data[k] != old.get(k, data[k])
                    )
                    for k in changes
                    if k != "fileIds"
                ) or (
                    "fileIds" in changes and data["fileIds"] != repo.attachment_ids(assignment_id)
                ):
                    raise ApiError(
                        409, "PUBLISHED_CONTENT_LOCKED", "Published content cannot be edited."
                    )
                if data["status"] not in ("PUBLISHED", "ARCHIVED"):
                    raise ApiError(
                        409, "PUBLISHED_CONTENT_LOCKED", "Published work cannot return to draft."
                    )
                changed = data["dueAt"] != old["dueAt"] or data["cutoffAt"] != old["cutoffAt"]
                if changed and (
                    data["dueAt"] < old["dueAt"]
                    or data["cutoffAt"] < old["cutoffAt"]
                    or repo.has_grade(assignment_id)
                ):
                    raise ApiError(
                        409,
                        "DEADLINE_LOCKED",
                        "Only deadline extensions before grading are allowed.",
                    )
            self._validate_assignment(sql, actor, row["offering_id"], data, assignment_id)
            repo.update_assignment(assignment_id, data)
            sql.execute(
                "UPDATE assignments SET group_formation=%s WHERE activity_id=%s",
                data.get("groupFormation", old["groupFormation"]),
                assignment_id,
            )
            repo.set_attachments(assignment_id, data["fileIds"])
            for file_id in data["fileIds"]:
                ContentRepository(sql).attach_file(file_id)
            offering_id = row["offering_id"]
            if old["status"] == "DRAFT" and data["status"] == "PUBLISHED":
                _notify_published(sql, actor, offering_id, assignment_id, data["title"])
            elif old["status"] == "PUBLISHED" and data["dueAt"] != old["dueAt"]:
                notify_course(
                    sql,
                    offering_id=offering_id,
                    actor_id=actor.user_id,
                    event_type="DUE_DATE_CHANGED",
                    title=data["title"],
                    target_type="ASSIGNMENT",
                    target_id=assignment_id,
                    event_key=f"DUE_DATE_CHANGED:{assignment_id}:{data['dueAt'].isoformat()}",
                )
            return self._assignment_view(sql, repo.get_assignment(assignment_id))

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

    def prepare_attachment(self, *, actor, offering_id, file_name, content_type, stream):
        return stage_file(
            self.database,
            self.storage,
            check=lambda sql: require_teacher(CourseRepository(sql), actor, offering_id),
            actor=actor,
            offering_id=offering_id,
            purpose="ASSIGNMENT_ATTACHMENT",
            assignment_id=None,
            file_name=file_name,
            content_type=content_type,
            stream=stream,
            max_bytes=20_000_000,
            limit_text="Assignment attachments can be at most 20 MB each.",
        )

    def confirm_submission(
        self,
        *,
        actor: Actor,
        assignment_id: int,
        expected_version: int,
        file_ids: list[int],
        request_key: str,
        group_id: int | None = None,
    ) -> dict[str, Any]:
        """Create one version. A client must send its confirmation request_key: sending the same key
        again (e.g. after a lost response) returns the earlier hand-in instead of a new one."""
        if not 1 <= len(file_ids) <= MAX_SUBMISSION_FILES or len(set(file_ids)) != len(file_ids):
            raise ApiError(400, "INVALID_REQUEST", "Submit 1 to 5 different files.")
        with self.database.transaction() as connection:
            sql = Sql(connection)
            repo = AssessmentRepository(sql)
            row = repo.get_assignment(assignment_id)
            if row is None:
                raise not_found("Assignment")
            require_member(CourseRepository(sql), actor, row["offering_id"])
            CourseRepository(sql).get_offering(row["offering_id"], lock=True)
            row = repo.get_assignment(assignment_id, lock=True)
            actual_group = (
                GroupRepository(sql).group_of(assignment_id, actor.user_id)
                if row["is_group_work"]
                else None
            )
            if group_id is not None and group_id != actual_group:
                raise ApiError(409, "GROUP_CHANGED", "Reload your current group before submitting.")
            import json

            fingerprint = hashlib.sha256(
                json.dumps(
                    [assignment_id, actual_group, expected_version, file_ids], separators=(",", ":")
                ).encode()
            ).hexdigest()
            accepted = (
                sql.one(
                    "SELECT * FROM submission_versions WHERE submitted_by=%s AND request_key=%s",
                    actor.user_id,
                    request_key,
                )
                if request_key
                else None
            )
            if accepted:
                original = repo.get_submission(accepted["submission_id"])
                receipt = self._receipt(sql, accepted)
                original_fingerprint = hashlib.sha256(
                    json.dumps(
                        [
                            original["assignment_id"],
                            original["group_id"],
                            accepted["version_no"] - 1,
                            receipt["fileIds"],
                        ],
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest()
                if original_fingerprint != fingerprint:
                    raise ApiError(
                        409,
                        "IDEMPOTENCY_KEY_REUSED",
                        "This confirmation key belongs to a different request.",
                    )
                earlier = self._view(sql, repo.get_submission(accepted["submission_id"]))
                earlier["currentVersion"] = self._receipt(sql, accepted)
                earlier["version"] = accepted["version_no"]
                return earlier
            self._can_submit_to(actor, row["offering_id"], assignment_id)(sql)
            row = repo.get_assignment(assignment_id, lock=True)
            assignment = assignment_from_row(row)

            group_id = None
            if row["is_group_work"]:  # the group's one submission
                group_id = GroupRepository(sql).group_of(assignment_id, actor.user_id)
                stream = GroupRepository(sql).lock_group_submission(group_id)
            else:
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

            if stream:
                submission_id = stream["submission_id"]
            elif group_id is not None:
                submission_id = GroupRepository(sql).insert_group_submission(
                    assignment_id, group_id
                )
            else:
                submission_id = repo.insert_submission(
                    assignment_id=assignment_id, student_id=actor.user_id
                )
            now = repo.db_now()
            if not assignment.is_open(now):
                raise ApiError(409, "SUBMISSION_WINDOW_CLOSED", "The submission cutoff has passed.")
            repo.insert_version(
                submission_id=submission_id,
                version_no=current + 1,
                submitted_by=actor.user_id,
                submitted_at=now,
                is_late=assignment.is_late(now),
                receipt_code="R-" + secrets.token_hex(8).upper(),
                request_key=request_key,
                request_hash=fingerprint,
                file_ids=file_ids,
            )
            for file_id in file_ids:
                files.attach_file(file_id)
            if group_id is not None and current == 0:  # first hand-in fixes the members
                GroupRepository(sql).freeze_roster(submission_id, group_id)
            AuditRepository(sql).record(
                actor_id=actor.user_id,
                action="SUBMISSION_CONFIRMED",
                target_type="SUBMISSION",
                target_id=submission_id,
                details={"versionNo": current + 1, "files": len(file_ids)},
            )
            return self._view(sql, repo.get_submission(submission_id))

    def get_my_submission(self, *, actor: Actor, assignment_id: int) -> dict[str, Any]:
        with self.database.transaction() as connection:
            sql = Sql(connection)
            assignment, _ = self._visible_assignment(sql, actor, assignment_id)
            repo = AssessmentRepository(sql)
            if assignment["is_group_work"]:
                group_id = GroupRepository(sql).group_of(assignment_id, actor.user_id)
                row = repo.find_group_submission(group_id) if group_id else None
            else:
                row = repo.find_submission(assignment_id=assignment_id, student_id=actor.user_id)
            if row is None:
                raise ApiError(404, "NOT_SUBMITTED", "You have not submitted anything yet.")
            return self._view(sql, row)

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
            membership = require_member(CourseRepository(sql), actor, row["offering_id"])
            if not is_teacher(membership):
                raise ApiError(403, "FORBIDDEN", "Teaching membership is required.")
            rows, total = repo.list_submissions(
                assignment_id, offset=(page - 1) * page_size, limit=page_size
            )
            return _page([self._view(sql, r) for r in rows], page, page_size, total)

    def get_submission(self, *, actor: Actor, submission_id: int) -> dict[str, Any]:
        """The student who owns it, or the class professor."""
        with self.database.transaction() as connection:
            sql = Sql(connection)
            repo = AssessmentRepository(sql)
            row = repo.get_submission(submission_id)
            if row is None:
                raise not_found("Submission")
            assignment = repo.get_assignment(row["assignment_id"])
            member = require_member(CourseRepository(sql), actor, assignment["offering_id"])
            view = self._view(sql, row)
            if actor.user_id not in view["recipientStudentIds"] and not is_teacher(member):
                raise not_found("Submission")
            return view

    def get_submission_history(self, *, actor, submission_id):
        with self.database.transaction() as connection:
            sql = Sql(connection)
            repo = AssessmentRepository(sql)
            row = repo.get_submission(submission_id)
            if row is None:
                raise not_found("Submission")
            assignment = repo.get_assignment(row["assignment_id"])
            member = require_member(CourseRepository(sql), actor, assignment["offering_id"])
            view = self._view(sql, row)
            if actor.user_id not in view["recipientStudentIds"] and not is_teacher(member):
                raise not_found("Submission")
            versions = sql.all(
                "SELECT version_no,submitted_by,submitted_at,is_late,receipt_code FROM submission_versions WHERE submission_id=%s ORDER BY version_no DESC",
                submission_id,
            )
            history = []
            files = []
            from app.services.content_service import file_view

            for v in versions:
                ids = [
                    f["file_id"]
                    for f in sql.all(
                        "SELECT file_id FROM submission_files WHERE submission_id=%s AND version_no=%s ORDER BY file_no",
                        submission_id,
                        v["version_no"],
                    )
                ]
                history.append(
                    {
                        "submissionId": submission_id,
                        "versionNo": v["version_no"],
                        "fileIds": ids,
                        "submittedByStudentId": v["submitted_by"],
                        "submittedAt": v["submitted_at"],
                        "isLate": bool(v["is_late"]),
                        "receiptCode": v["receipt_code"],
                    }
                )
                files.extend(file_view(ContentRepository(sql).get_file(i)) for i in ids)
            from app.infrastructure.db.repositories.identity_repository import IdentityRepository
            from app.services.auth_service import account_view

            identity = IdentityRepository(sql)
            owners = [identity.get_account(i) for i in view["recipientStudentIds"]]
            from app.infrastructure.db.repositories.grading_repository import GradingRepository
            from app.services.grading_service import GradingService

            grade_row = GradingRepository(sql).lock_grade(submission_id)
            grade = (
                GradingService(self.database)._record(sql, actor, grade_row["grade_id"])
                if grade_row
                and (is_teacher(member) or grade_row["published_revision_no"] is not None)
                else None
            )
            return {
                "submission": view,
                "history": history,
                "files": list({f["id"]: f for f in files}.values()),
                "recipients": [account_view(o)["account"] for o in owners if o],
                "grade": grade,
                "revisions": grade["revisions"]
                if grade and grade["revisions"]
                else ([grade["publishedRevision"]] if grade and grade["publishedRevision"] else []),
            }

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _view(sql: Sql, row: dict[str, Any]) -> dict[str, Any]:
        members = (
            GroupRepository(sql).submission_members(row["submission_id"])
            if row["group_id"]
            else None
        )
        return utc_payload(submission_view(row, members))

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
            repo = AssessmentRepository(sql)
            row = repo.get_assignment(assignment_id, lock=True)
            if row["status"] != PublishStatus.PUBLISHED:
                raise not_found("Assignment")
            if not assignment_from_row(row).is_open(repo.db_now()):
                raise ApiError(
                    409,
                    "SUBMISSION_WINDOW_CLOSED",
                    "Submissions are accepted only between opening and cutoff.",
                )
            if (
                row["is_group_work"]
                and GroupRepository(sql).group_of(assignment_id, actor.user_id) is None
            ):
                raise ApiError(409, "NO_GROUP", "Join or create a group before handing in.")
            if repo.student_has_grade(assignment_id, actor.user_id):
                raise ApiError(409, "DEADLINE_LOCKED", "Graded work cannot be resubmitted.")

        return check

    @staticmethod
    def _receipt(sql, version):
        files = sql.all(
            "SELECT file_id FROM submission_files WHERE submission_id=%s AND version_no=%s ORDER BY file_no",
            version["submission_id"],
            version["version_no"],
        )
        return {
            "submissionId": version["submission_id"],
            "versionNo": version["version_no"],
            "fileIds": [f["file_id"] for f in files],
            "submittedByStudentId": version["submitted_by"],
            "submittedAt": version["submitted_at"],
            "isLate": bool(version["is_late"]),
            "receiptCode": version["receipt_code"],
        }

    def get_submission_receipt(self, *, actor, assignment_id, key):
        with self.database.transaction() as connection:
            sql = Sql(connection)
            self._visible_assignment(sql, actor, assignment_id)
            version = sql.one(
                """SELECT v.* FROM submission_versions v JOIN submissions s ON s.submission_id=v.submission_id
                WHERE s.assignment_id=%s AND v.submitted_by=%s AND v.request_key=%s""",
                assignment_id,
                actor.user_id,
                key,
            )
            if version is None:
                raise not_found("Receipt")
            return self._receipt(sql, version)


def _notify_published(sql, actor, offering_id, assignment_id, title) -> None:
    notify_course(
        sql,
        offering_id=offering_id,
        actor_id=actor.user_id,
        event_type="ASSIGNMENT_PUBLISHED",
        title=title,
        target_type="ASSIGNMENT",
        target_id=assignment_id,
        event_key=f"ASSIGNMENT_PUBLISHED:{assignment_id}",
    )


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
