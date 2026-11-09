import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePath
from typing import Any, BinaryIO

from app.core.errors import (
    ApiError,
    FeatureNotImplemented,
    conflict,
    not_found,
    version_conflict,
)
from app.domain.context import Actor
from app.infrastructure.db.repositories.assessment_repository import AssessmentRepository
from app.infrastructure.db.repositories.audit_repository import AuditRepository
from app.infrastructure.db.repositories.content_repository import (
    ContentRepository,
)
from app.infrastructure.db.repositories.course_repository import CourseRepository
from app.infrastructure.db.sql import Sql, is_unique_violation
from app.infrastructure.file_storage import EmptyFile, FileStorage, FileTooLarge
from app.services.access import is_teacher, require_member, require_student, require_teacher

MAX_MATERIAL_BYTES = 50_000_000  # report: materials up to 50MB (decimal)
_URL = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class Download:
    path: Path
    file_name: str
    mime_type: str


def topic_view(topic) -> dict[str, Any]:
    return {
        "id": topic.topic_id,
        "offeringId": topic.offering_id,
        "title": topic.title,
        "position": topic.position,
        "version": topic.version,
    }


def file_view(row: dict[str, Any]) -> dict[str, Any]:
    """FileAsset response shape (OpenAPI contract)."""
    return {
        "id": row["file_id"],
        "offeringId": row["offering_id"],
        "originalName": row["file_name"],
        "mediaType": row["mime_type"],
        "byteSize": row["size_bytes"],
        "sha256": row["sha256"],
        "state": row["state"],
        "leaseExpiresAt": row["expires_at"],
        "purpose": row["purpose"],
    }


def material_view(row: dict[str, Any]) -> dict[str, Any]:
    """Resource response shape (OpenAPI contract)."""
    return {
        "id": row["material_id"],
        "offeringId": row["offering_id"],
        "topicId": row["topic_id"],
        "title": row["title"],
        "kind": row["kind"],
        "status": row["status"],
        "body": row["body"],
        "externalUrl": row["url"],
        "fileIds": [row["file_id"]] if row["file_id"] else [],
        "version": row["version"],
    }


def clean_file_name(name: str | None) -> str:
    """Keep only the last path part, drop control characters, cap at 255."""
    base = PurePath((name or "").replace("\\", "/")).name
    base = _CONTROL.sub("", base).strip()
    return (base or "file")[:255]


def stage_file(
    database,
    storage: FileStorage,
    *,
    check: Callable[[Sql], object],
    actor: Actor,
    offering_id: int,
    purpose: str,
    assignment_id: int | None,
    file_name: str | None,
    content_type: str | None,
    stream: BinaryIO,
    max_bytes: int,
    limit_text: str,
) -> dict[str, Any]:
    """Shared upload step: permission check, bytes to FileStorage, STAGING FileAsset row.

    `check` runs before any bytes are taken and again inside the insert transaction.
    If the row cannot be written the stored bytes are deleted, so nothing is orphaned.
    """
    with database.transaction() as connection:
        check(Sql(connection))
    try:
        stored = storage.save(stream, max_bytes=max_bytes)
    except FileTooLarge:
        raise ApiError(413, "FILE_TOO_LARGE", limit_text) from None
    except EmptyFile:
        raise ApiError(400, "EMPTY_FILE", "The file is empty.") from None
    try:
        with database.transaction() as connection:
            sql = Sql(connection)
            check(sql)
            row = ContentRepository(sql).insert_file_asset(
                offering_id=offering_id,
                uploaded_by=actor.user_id,
                purpose=purpose,
                assignment_id=assignment_id,
                file_key=stored.key,
                file_name=clean_file_name(file_name),
                mime_type=(content_type or "application/octet-stream")[:127],
                size_bytes=stored.size_bytes,
                sha256=stored.sha256,
            )
    except BaseException:
        storage.delete(stored.key)
        raise
    return file_view(row)


def _page(items: list, page: int, page_size: int, total: int) -> dict[str, Any]:
    return {
        "items": items,
        "page": page,
        "pageSize": page_size,
        "totalItems": total,
        "totalPages": (total + page_size - 1) // page_size,
    }


class ContentService:
    def __init__(self, database=None, storage: FileStorage | None = None):
        self.database = database
        self.storage = storage

    # ------------------------------------------------------------------ topics
    def create_topic(
        self, *, actor: Actor, offering_id: int, title: str, position: int | None = None
    ) -> dict[str, Any]:
        title = title.strip()
        if not title:
            raise ApiError(400, "INVALID_REQUEST", "Topic title must not be blank.")
        try:
            with self.database.transaction() as connection:
                sql = Sql(connection)
                require_teacher(CourseRepository(sql), actor, offering_id)
                repo = ContentRepository(sql)
                next_position = repo.next_topic_position(offering_id)
                count = sql.scalar(
                    "SELECT COUNT(*) FROM dbo.topics WHERE offering_id=?", offering_id
                )
                target = position if position is not None else count + 1
                if not 1 <= target <= count + 1:
                    raise ApiError(400, "INVALID_POSITION", "Topic order must fit the topic list.")
                topic = repo.insert_topic(
                    offering_id=offering_id, title=title, position=next_position
                )
                if target != next_position:
                    repo.reorder_topic(topic.topic_id, title, target)
                    topic = repo.get_topic(topic.topic_id)
        except Exception as error:
            if is_unique_violation(error):
                raise conflict(
                    "POSITION_TAKEN", "Another topic already has this position."
                ) from None
            raise
        return topic_view(topic)

    def list_topics(
        self, *, actor: Actor, offering_id: int, page: int, page_size: int
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            sql = Sql(connection)
            require_member(CourseRepository(sql), actor, offering_id)
            topics, total = ContentRepository(sql).list_topics(
                offering_id, offset=(page - 1) * page_size, limit=page_size
            )
        return _page([topic_view(t) for t in topics], page, page_size, total)

    # ------------------------------------------------------------------- files
    def prepare_file(
        self,
        *,
        actor: Actor,
        offering_id: int,
        purpose: str,
        file_name: str | None,
        content_type: str | None,
        stream: BinaryIO,
    ) -> dict[str, Any]:
        """Upload step 1 for materials: a STAGING file of the class (24h to attach)."""
        if purpose != "MATERIAL":
            raise ApiError(400, "INVALID_REQUEST", "Use purpose MATERIAL or SUBMISSION.")
        return stage_file(
            self.database,
            self.storage,
            check=lambda sql: require_teacher(CourseRepository(sql), actor, offering_id),
            actor=actor,
            offering_id=offering_id,
            purpose=purpose,
            assignment_id=None,
            file_name=file_name,
            content_type=content_type,
            stream=stream,
            max_bytes=MAX_MATERIAL_BYTES,
            limit_text="Materials can be at most 50 MB.",
        )

    def download_file(self, *, actor: Actor, file_id: int) -> Download:
        """downloadMaterial: members get files of published materials; teachers get all,
        and the uploader can fetch a still-staging upload. Submission files are checked
        by SubmissionService."""
        from app.services.submission_service import check_submission_file_access

        with self.database.transaction() as connection:
            sql = Sql(connection)
            repo = ContentRepository(sql)
            file = repo.get_file(file_id)
            if file is None or file["purpose"] not in (
                "MATERIAL",
                "SUBMISSION",
                "ASSIGNMENT_ATTACHMENT",
            ):
                raise not_found("File")
            member = require_member(CourseRepository(sql), actor, file["offering_id"])
            if file["state"] == "EXPIRED":
                raise not_found("File")
            if file["state"] == "STAGING":
                if file["expires_at"] <= AssessmentRepository(sql).db_now():
                    raise not_found("File")
                if file["uploaded_by"] != actor.user_id:
                    raise not_found("File")
            elif file["purpose"] == "ASSIGNMENT_ATTACHMENT":
                assignment_id = sql.scalar(
                    "SELECT assignment_id FROM dbo.assignment_attachments WHERE file_id=?", file_id
                )
                row = (
                    AssessmentRepository(sql).get_assignment(assignment_id)
                    if assignment_id
                    else None
                )
                if row is None or (not is_teacher(member) and row["status"] != "PUBLISHED"):
                    raise not_found("File")
            elif file["purpose"] == "SUBMISSION":
                check_submission_file_access(sql, actor, file)
            else:
                material = repo.material_for_file(file_id)
                if material is None:
                    raise not_found("File")
                member = require_member(CourseRepository(sql), actor, material["offering_id"])
                if not is_teacher(member) and material["status"] != "PUBLISHED":
                    raise not_found("File")
        return Download(
            path=self.storage.path_for(file["file_key"]),
            file_name=file["file_name"],
            mime_type=file["mime_type"],
        )

    # --------------------------------------------------------------- materials
    def _view(self, sql, actor, row):
        view = material_view(row)
        repo = ContentRepository(sql)
        view["mandatory"] = bool(row["is_mandatory"])
        view["completed"] = repo.completed(actor.user_id, row["material_id"])
        view["files"] = [file_view(repo.get_file(i)) for i in view["fileIds"]]
        return view

    def _validate(self, sql, actor, offering_id, data, old_file_id=None):
        if not data["title"].strip():
            raise ApiError(400, "INVALID_REQUEST", "Title must not be blank.")
        data["title"] = data["title"].strip()
        topic = ContentRepository(sql).get_topic(data["topicId"])
        if topic is None or topic.offering_id != offering_id:
            raise ApiError(422, "TOPIC_NOT_FOUND", "Topic must belong to the class.")
        if data["kind"] == "TEXT":
            if (
                not data.get("body", "")
                or not data["body"].strip()
                or data.get("externalUrl")
                or data.get("fileIds")
            ):
                raise ApiError(400, "INVALID_REQUEST", "TEXT requires a nonempty body only.")
        elif data["kind"] == "LINK":
            if (
                not data.get("externalUrl")
                or not _URL.match(data["externalUrl"])
                or data.get("fileIds")
                or data.get("body")
            ):
                raise ApiError(400, "INVALID_REQUEST", "LINK requires an http(s) URL only.")
        elif data["kind"] == "FILE":
            if len(data.get("fileIds") or []) != 1 or data.get("externalUrl") or data.get("body"):
                raise ApiError(400, "INVALID_REQUEST", "FILE requires one uploaded file only.")
            file = ContentRepository(sql).get_file(data["fileIds"][0], lock=True)
            if not (file and file["file_id"] == old_file_id and file["state"] == "ATTACHED"):
                _check_staged_file(file, offering_id)
                if file["uploaded_by"] != actor.user_id:
                    raise ApiError(422, "FILE_NOT_USABLE", "Use your own upload.")
        else:
            raise ApiError(400, "INVALID_REQUEST", "Unknown material kind.")

    def save_material(self, *, actor, offering_id, data):
        with self.database.transaction() as connection:
            sql = Sql(connection)
            require_teacher(CourseRepository(sql), actor, offering_id)
            self._validate(sql, actor, offering_id, data)
            repo = ContentRepository(sql)
            material_id = repo.insert_material(data=data)
            if data["kind"] == "FILE":
                repo.attach_file(data["fileIds"][0])
            AuditRepository(sql).record(
                actor_id=actor.user_id,
                action="MATERIAL_CREATED",
                target_type="MATERIAL",
                target_id=material_id,
                details={"kind": data["kind"], "status": data["status"]},
            )
            return self._view(sql, actor, repo.get_material(material_id))

    def list_materials(self, *, actor, offering_id, page, page_size):
        with self.database.transaction() as connection:
            sql = Sql(connection)
            member = require_member(CourseRepository(sql), actor, offering_id)
            rows, total = ContentRepository(sql).list_materials(
                offering_id,
                published_only=not is_teacher(member),
                offset=(page - 1) * page_size,
                limit=page_size,
            )
            return _page([self._view(sql, actor, r) for r in rows], page, page_size, total)

    def get_material(self, *, actor, material_id):
        with self.database.transaction() as connection:
            sql = Sql(connection)
            row = ContentRepository(sql).get_material(material_id)
            if row is None:
                raise not_found("Material")
            member = require_member(CourseRepository(sql), actor, row["offering_id"])
            if not is_teacher(member) and row["status"] != "PUBLISHED":
                raise not_found("Material")
            return self._view(sql, actor, row)

    def update_material(self, *, actor, material_id, expected_version, changes):
        with self.database.transaction() as connection:
            sql = Sql(connection)
            repo = ContentRepository(sql)
            row = repo.get_material(material_id)
            if row is None:
                raise not_found("Material")
            require_teacher(CourseRepository(sql), actor, row["offering_id"])
            row = repo.get_material(material_id, lock=True)
            if row["version"] != expected_version:
                raise version_conflict(row["version"])
            old = material_view(row)
            data = {
                k: old[k]
                for k in ["title", "topicId", "kind", "status", "body", "externalUrl", "fileIds"]
            }
            data["mandatory"] = bool(row["is_mandatory"])
            data.update(changes)
            self._validate(sql, actor, row["offering_id"], data, row["file_id"])
            repo.update_material(material_id, data)
            if data["kind"] == "FILE":
                repo.attach_file(data["fileIds"][0])
            return self._view(sql, actor, repo.get_material(material_id))

    def update_topic(self, *, actor, topic_id, expected_version, title, position):
        try:
            with self.database.transaction() as connection:
                sql = Sql(connection)
                repo = ContentRepository(sql)
                topic = repo.get_topic(topic_id)
                if topic is None:
                    raise not_found("Topic")
                require_teacher(CourseRepository(sql), actor, topic.offering_id)
                topic = repo.get_topic(topic_id)
                if topic.version != expected_version:
                    raise version_conflict(topic.version)
                if not title.strip():
                    raise ApiError(400, "INVALID_REQUEST", "Title must not be blank.")
                count = sql.scalar(
                    "SELECT COUNT(*) FROM dbo.topics WHERE offering_id=?", topic.offering_id
                )
                target = position or topic.position
                if not 1 <= target <= count:
                    raise ApiError(400, "INVALID_POSITION", "Topic order must fit the topic list.")
                repo.reorder_topic(topic_id, title.strip(), target)
                return topic_view(repo.get_topic(topic_id))
        except Exception as error:
            if is_unique_violation(error):
                raise conflict(
                    "POSITION_TAKEN", "Another topic already uses this position."
                ) from None
            raise

    def set_completion(self, *, actor, material_id, complete):
        with self.database.transaction() as connection:
            sql = Sql(connection)
            repo = ContentRepository(sql)
            row = repo.get_material(material_id)
            if row is None:
                raise not_found("Material")
            require_student(CourseRepository(sql), actor, row["offering_id"])
            row = repo.get_material(material_id, lock=True)
            if row["status"] != "PUBLISHED":
                raise not_found("Material")
            repo.set_completion(actor.user_id, material_id, complete)
            return self._view(sql, actor, row)

    def get_file(self, *, actor, file_id):
        self.download_file(actor=actor, file_id=file_id)
        with self.database.read_connection() as connection:
            return file_view(ContentRepository(Sql(connection)).get_file(file_id))

    # ------------------------------------------- placeholders behind 501 routes
    def create_announcement(self, **kwargs: object):
        raise FeatureNotImplemented("ContentService.create_announcement")

    def list_announcements(self, **kwargs: object):
        raise FeatureNotImplemented("ContentService.list_announcements")


def _check_staged_file(file: dict[str, Any] | None, offering_id: int) -> None:
    if (
        file is None
        or file["purpose"] != "MATERIAL"
        or file["offering_id"] != offering_id
        or file["state"] != "STAGING"
    ):
        raise ApiError(422, "FILE_NOT_USABLE", "Upload the file to this class first.")
    if file["expires_at"] <= datetime.now(UTC):
        raise ApiError(422, "FILE_NOT_USABLE", "The upload expired; upload it again.")
