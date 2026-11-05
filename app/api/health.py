from fastapi import APIRouter, Request

from app.core.errors import problem
from app.infrastructure.db.connection import DatabaseUnavailable

router = APIRouter(tags=["Health"])


@router.get("/health/live")
def live():
    return {"status": "alive"}


@router.get("/health/ready")
def ready(request: Request):
    try:
        request.app.state.database.check_connection()
    except DatabaseUnavailable:
        return problem(
            503, "DATABASE_UNAVAILABLE", "Database connection is unavailable.", "/health/ready"
        )
    return problem(
        503,
        "SCHEMA_NOT_INSTALLED",
        "SQL Server reachable; reviewed SQL schema/business services are not implemented yet.",
        "/health/ready",
    )
