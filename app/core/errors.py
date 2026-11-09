from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException


class FeatureNotImplemented(Exception):
    def __init__(self, target: str):
        self.target = target
        super().__init__(target)


class PolicyNotImplemented(FeatureNotImplemented):
    pass


class ApiError(Exception):
    """Business error rendered as application/problem+json. Detail must be safe to show users."""

    def __init__(self, status: int, code: str, detail: str, *, current_version: int | None = None):
        self.status = status
        self.code = code
        self.detail = detail
        self.current_version = current_version
        super().__init__(code)


def unauthenticated() -> ApiError:
    return ApiError(401, "UNAUTHENTICATED", "Sign in to continue.")


def forbidden(detail: str = "You do not have permission for this action.") -> ApiError:
    return ApiError(403, "FORBIDDEN", detail)


def not_found(what: str = "Resource") -> ApiError:
    return ApiError(404, "NOT_FOUND", f"{what} was not found.")


def conflict(code: str, detail: str) -> ApiError:
    return ApiError(409, code, detail)


def version_conflict(current_version: int) -> ApiError:
    return ApiError(
        412,
        "VERSION_CONFLICT",
        "This item was changed by someone else. Reload and try again.",
        current_version=current_version,
    )


def problem(
    status: int,
    code: str,
    detail: str,
    instance: str,
    *,
    current_version: int | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    content = {
        "type": f"urn:elio:problem:{code.lower()}",
        "title": code.replace("_", " ").title(),
        "status": status,
        "code": code,
        "detail": detail,
        "instance": instance,
        "traceId": uuid4().hex,
    }
    if current_version is not None:
        content["currentVersion"] = current_version
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content=content,
        headers=headers,
    )


def install_error_handlers(app: FastAPI) -> None:
    from app.infrastructure.db.connection import DatabaseUnavailable

    @app.exception_handler(DatabaseUnavailable)
    async def database_unavailable(request: Request, exc: DatabaseUnavailable):
        return problem(
            503, "DATABASE_UNAVAILABLE", "Database connection is unavailable.", request.url.path
        )

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        headers = {"ETag": f'"{exc.current_version}"'} if exc.current_version else None
        return problem(
            exc.status,
            exc.code,
            exc.detail,
            request.url.path,
            current_version=exc.current_version,
            headers=headers,
        )

    @app.exception_handler(FeatureNotImplemented)
    async def unimplemented(request: Request, exc: FeatureNotImplemented):
        return problem(
            501,
            "NOT_IMPLEMENTED",
            f"Operation unavailable: {exc.target}.",
            request.url.path,
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        # Never echo password/private request input in validation details.
        return problem(400, "INVALID_REQUEST", "Request validation failed.", request.url.path)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return problem(
            exc.status_code,
            "HTTP_ERROR",
            "The requested operation is unavailable or invalid.",
            request.url.path,
        )
