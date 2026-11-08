"""ContentService from the class diagram: topics, materials (FILE / LINK) and their files.

Who may do what:
- the class professor (active PRIMARY_INSTRUCTOR) creates topics, uploads files, creates and
  edits materials, and sees drafts;
- active class members (students) see and download PUBLISHED materials only;
- everyone else, admins included, gets 404: admin operational access does not include
  reading course content.
"""

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
from app.domain.entities import (
    MaterialKind,
    PublishStatus,
)
from app.infrastructure.db.repositories.audit_repository import AuditRepository
from app.infrastructure.db.repositories.content_repository import (
    ContentRepository,
    material_from_row,
)
from app.infrastructure.db.repositories.course_repository import CourseRepository
from app.infrastructure.db.sql import Sql, is_unique_violation
from app.infrastructure.file_storage import EmptyFile, FileStorage, FileTooLarge
from app.services.access import is_teacher, require_member, require_teacher

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
        "body": None,
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
                topic = repo.insert_topic(
                    offering_id=offering_id,
                    title=title,
                    position=position or repo.next_topic_position(offering_id),
                )
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
            if file is None or file["purpose"] not in ("MATERIAL", "SUBMISSION"):
                raise not_found("File")
            if file["state"] == "STAGING":
                if file["uploaded_by"] != actor.user_id:
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
    def save_material(
        self,
        *,
        actor: Actor,
        offering_id: int,
        topic_id: int,
        kind: str,
        title: str,
        status: str,
        external_url: str | None,
        file_ids: list[int] | None,
    ) -> dict[str, Any]:
        """Upload step 2: a FILE material attaches one staged file; a LINK keeps a URL."""
        title = title.strip()
        if not title:
            raise ApiError(400, "INVALID_REQUEST", "Title must not be blank.")
        if kind not in (MaterialKind.FILE, MaterialKind.LINK):
            raise ApiError(400, "INVALID_REQUEST", "Materials are FILE or LINK.")
        if status not in (PublishStatus.DRAFT, PublishStatus.PUBLISHED):
            raise ApiError(400, "INVALID_REQUEST", "Status must be DRAFT or PUBLISHED.")
        if kind == MaterialKind.LINK:
            if not external_url or not _URL.match(external_url) or file_ids:
                raise ApiError(400, "INVALID_REQUEST", "A LINK needs one http(s) externalUrl.")
        elif external_url or not file_ids or len(file_ids) != 1:
            raise ApiError(400, "INVALID_REQUEST", "A FILE material needs exactly one fileId.")

        with self.database.transaction() as connection:
            sql = Sql(connection)
            require_teacher(CourseRepository(sql), actor, offering_id)
            repo = ContentRepository(sql)
            topic = repo.get_topic(topic_id)
            if topic is None or topic.offering_id != offering_id:
                raise ApiError(422, "TOPIC_NOT_FOUND", "The topic is not in this class.")
            file_id = None
            if kind == MaterialKind.FILE:
                file_id = file_ids[0]
                _check_staged_file(repo.get_file(file_id, lock=True), offering_id)
                repo.attach_file(file_id)
            material_id = repo.insert_material(
                topic_id=topic_id,
                kind=MaterialKind(kind),
                title=title,
                status=PublishStatus(status),
                url=external_url,
                file_id=file_id,
            )
            AuditRepository(sql).record(
                actor_id=actor.user_id,
                action="MATERIAL_CREATED",
                target_type="MATERIAL",
                target_id=material_id,
                details={"kind": kind, "status": status},
            )
            row = repo.get_material(material_id)
        return material_view(row)

    def list_materials(
        self, *, actor: Actor, offering_id: int, page: int, page_size: int
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            sql = Sql(connection)
            member = require_member(CourseRepository(sql), actor, offering_id)
            rows, total = ContentRepository(sql).list_materials(
                offering_id,
                published_only=not is_teacher(member),
                offset=(page - 1) * page_size,
                limit=page_size,
            )
        return _page([material_view(r) for r in rows], page, page_size, total)

    def get_material(self, *, actor: Actor, material_id: int) -> dict[str, Any]:
        with self.database.transaction() as connection:
            sql = Sql(connection)
            row = ContentRepository(sql).get_material(material_id)
            if row is None:
                raise not_found("Material")
            member = require_member(CourseRepository(sql), actor, row["offering_id"])
            if not is_teacher(member) and row["status"] != "PUBLISHED":
                raise not_found("Material")
        return material_view(row)

    def update_material(
        self,
        *,
        actor: Actor,
        material_id: int,
        expected_version: int,
        title: str | None,
        status: str | None,
    ) -> dict[str, Any]:
        """Rename and/or publish (publishMaterial) or unpublish; needs the current version."""
        with self.database.transaction() as connection:
            sql = Sql(connection)
            repo = ContentRepository(sql)
            row = repo.get_material(material_id, lock=True)
            if row is None:
                raise not_found("Material")
            require_teacher(CourseRepository(sql), actor, row["offering_id"])
            if row["version"] != expected_version:
                raise version_conflict(row["version"])
            material = material_from_row(row)
            if title is not None:
                if not title.strip():
                    raise ApiError(400, "INVALID_REQUEST", "Title must not be blank.")
                material.title = title.strip()
            if status == PublishStatus.PUBLISHED:
                material.publish()
            elif status is not None:
                material.status = PublishStatus(status)
            repo.update_material(material)
            row = repo.get_material(material_id)
        return material_view(row)

    # ------------------------------------------- placeholders behind 501 routes
    def create_announcement(self, **kwargs: object):
        raise FeatureNotImplemented("ContentService.create_announcement")

    def list_announcements(self, **kwargs: object):
        raise FeatureNotImplemented("ContentService.list_announcements")

    def update_topic(self, **kwargs: object):
        raise FeatureNotImplemented("ContentService.update_topic")


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
