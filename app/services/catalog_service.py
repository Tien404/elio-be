"""Catalog courses and sign-up requests (team MVP flow, see migration 006)."""

from decimal import Decimal
from typing import Any

from app.core.errors import ApiError, forbidden
from app.domain.context import Actor
from app.infrastructure.db.repositories.audit_repository import AuditRepository
from app.infrastructure.db.repositories.catalog_repository import (
    CatalogRepository,
    catalog_course_view,
)
from app.infrastructure.db.sql import Sql

DEGREE_DIGIT = {"UNDERGRADUATE": 0, "MASTERS": 1, "PHD": 2}
MAX_COURSE_NUMBER = 99


class CatalogService:
    def __init__(self, database):
        self.database = database

    def admin_create_course(
        self,
        *,
        actor: Actor,
        faculty_code: str,
        year_level: int,
        degree_level: str,
        course_name: str,
        credits: Decimal,
        description: str | None,
    ) -> dict[str, Any]:
        if actor.role != "ADMIN":
            raise forbidden()
        name = course_name.strip()
        if not name:
            raise ApiError(400, "INVALID_REQUEST", "Course name must not be blank.")
        stem = f"{faculty_code.upper()}{year_level}{DEGREE_DIGIT[degree_level]}"
        with self.database.transaction() as connection:
            sql = Sql(connection)
            repo = CatalogRepository(sql)
            number = (repo.max_course_number(stem) or 0) + 1
            if number > MAX_COURSE_NUMBER:
                raise ApiError(
                    409, "COURSE_CODE_EXHAUSTED", f"All codes {stem}01-{stem}99 are in use."
                )
            row = repo.insert_course(
                course_code=f"{stem}{number:02d}",
                course_name=name,
                credits=credits,
                description=(description or "").strip() or None,
            )
            AuditRepository(sql).record(
                actor_id=actor.user_id,
                action="COURSE_CREATED",
                target_type="COURSE",
                target_id=row["course_id"],
                details={"courseCode": row["course_code"]},
            )
        return catalog_course_view(row)
