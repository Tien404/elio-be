from pathlib import Path

from fastapi import APIRouter, Request

from app.core.errors import problem
from app.infrastructure.db.connection import DatabaseUnavailable

router = APIRouter(tags=["Health"])

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "sql" / "migrations"


def expected_migrations() -> set[str]:
    return {path.stem for path in MIGRATIONS_DIR.glob("*.sql")}


@router.get("/health/live")
def live():
    return {"status": "alive"}


@router.get("/health/ready")
def ready(request: Request):
    database = request.app.state.database
    try:
        database.check_connection()
        with database.read_connection() as connection:
            cursor = connection.cursor()
            try:
                has_table = cursor.execute(
                    "SELECT OBJECT_ID(N'dbo.schema_migrations', N'U')"
                ).fetchone()[0]
                applied = (
                    {
                        row[0]
                        for row in cursor.execute(
                            "SELECT migration_id FROM dbo.schema_migrations"
                        ).fetchall()
                    }
                    if has_table
                    else set()
                )
            finally:
                cursor.close()
    except DatabaseUnavailable:
        return problem(
            503, "DATABASE_UNAVAILABLE", "Database connection is unavailable.", "/health/ready"
        )
    except Exception:
        return problem(503, "DATABASE_UNAVAILABLE", "Database check failed.", "/health/ready")
    missing = expected_migrations() - applied
    if missing:
        return problem(
            503,
            "SCHEMA_NOT_INSTALLED",
            f"{len(missing)} migration(s) not applied; run sql/apply_migrations.ps1.",
            "/health/ready",
        )
    return {"status": "ready", "migrations": len(applied)}
