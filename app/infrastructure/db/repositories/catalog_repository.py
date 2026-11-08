"""T-SQL for catalog courses. Never commits; caller owns the transaction."""

from decimal import Decimal
from typing import Any

from app.infrastructure.db.sql import Sql


class CatalogRepository:
    def __init__(self, sql: Sql):
        self.sql = sql

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
    ) -> dict[str, Any]:
        return self.sql.one(
            """INSERT dbo.courses (course_code, course_name, credits, description)
               OUTPUT INSERTED.course_id, INSERTED.course_code, INSERTED.course_name,
                      INSERTED.credits
               VALUES (?, ?, ?, ?)""",
            course_code,
            course_name,
            credits,
            description,
        )


def catalog_course_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["course_id"],
        "courseCode": row["course_code"],
        "courseName": row["course_name"],
        "credits": float(row["credits"]),
    }
