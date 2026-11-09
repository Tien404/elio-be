from pathlib import Path

from fastapi import APIRouter, Request

from app.core.errors import problem
from app.infrastructure.db.connection import DatabaseUnavailable
from app.infrastructure.db.sql import Sql

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
            sql = Sql(connection)
            has_table = sql.scalar(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = 'schema_migrations'"
            )
            applied = (
                {
                    row["migration_id"]
                    for row in sql.all("SELECT migration_id FROM schema_migrations")
                }
                if has_table
                else set()
            )
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
            f"{len(missing)} migration(s) not applied; run python -m scripts.migrate.",
            "/health/ready",
        )
    return {"status": "ready", "migrations": len(applied)}
