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


def problem(status: int, code: str, detail: str, instance: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={
            "type": f"urn:elio:problem:{code.lower()}",
            "title": code.replace("_", " ").title(),
            "status": status,
            "code": code,
            "detail": detail,
            "instance": instance,
            "traceId": uuid4().hex,
        },
    )


def install_error_handlers(app: FastAPI) -> None:
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
