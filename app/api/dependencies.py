"""Request-scoped dependencies: services, cookie session, CSRF and If-Match parsing.

Order of checks for protected routes: session (401) -> restricted-session policy (403)
-> CSRF on mutations (403) -> service policy/state.
"""

from typing import Annotated

from fastapi import Depends, Header, Request, Response

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import csrf_matches
from app.domain.context import Actor, SessionContext
from app.infrastructure.file_storage import FileStorage
from app.services.auth_service import AuthService
from app.services.content_service import ContentService
from app.services.course_service import CourseService
from app.services.submission_service import SubmissionService


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_auth_service(request: Request) -> AuthService:
    return AuthService(request.app.state.database, request.app.state.settings)


def get_content_service(request: Request) -> ContentService:
    settings: Settings = request.app.state.settings
    return ContentService(request.app.state.database, FileStorage(settings.private_files_dir))


def get_submission_service(request: Request) -> SubmissionService:
    settings: Settings = request.app.state.settings
    return SubmissionService(request.app.state.database, FileStorage(settings.private_files_dir))


def get_course_service(request: Request) -> CourseService:
    return CourseService(request.app.state.database)


def _resolve(request: Request, service: AuthService) -> SessionContext:
    cached = getattr(request.state, "session", None)
    if cached is not None:
        return cached
    settings: Settings = request.app.state.settings
    token = request.cookies.get(settings.session_cookie_name)
    session = service.resolve_session(token)
    request.state.session = session
    return session


def session_allow_restricted(
    request: Request, service: Annotated[AuthService, Depends(get_auth_service)]
) -> SessionContext:
    """Any live session, including temporary-password sessions (logout/change password only)."""
    return _resolve(request, service)


def current_session(
    request: Request, service: Annotated[AuthService, Depends(get_auth_service)]
) -> SessionContext:
    session = _resolve(request, service)
    if session.actor.restricted:
        raise ApiError(
            403, "PASSWORD_CHANGE_REQUIRED", "Change your temporary password to continue."
        )
    return session


CsrfHeader = Annotated[
    str | None,
    Header(
        alias="X-CSRF-Token",
        description="Session-bound CSRF token from SessionView.csrfToken. Never logged.",
    ),
]


def _check_csrf(session: SessionContext, presented: str | None) -> None:
    if not csrf_matches(session.token, presented):
        raise ApiError(403, "CSRF_REJECTED", "Missing or invalid CSRF token.")


def mutation_session(
    session: Annotated[SessionContext, Depends(current_session)], x_csrf_token: CsrfHeader = None
) -> SessionContext:
    _check_csrf(session, x_csrf_token)
    return session


def mutation_session_allow_restricted(
    session: Annotated[SessionContext, Depends(session_allow_restricted)],
    x_csrf_token: CsrfHeader = None,
) -> SessionContext:
    _check_csrf(session, x_csrf_token)
    return session


def current_actor(session: Annotated[SessionContext, Depends(current_session)]) -> Actor:
    return session.actor


def mutation_actor(session: Annotated[SessionContext, Depends(mutation_session)]) -> Actor:
    return session.actor


IfMatchHeader = Annotated[
    str,
    Header(
        alias="If-Match",
        pattern=r'^"[1-9][0-9]*"$',
        description='ETag version you read, e.g. "3". Stale -> 412 VERSION_CONFLICT.',
    ),
]


def expected_version(if_match: IfMatchHeader) -> int:
    return int(if_match.strip('"'))


def set_etag(response: Response, version: int) -> None:
    response.headers["ETag"] = f'"{version}"'


def set_session_cookie(response: Response, settings: Settings, token: str, expires_at) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        token,
        expires=expires_at,
        path="/",
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
    )


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
CourseServiceDep = Annotated[CourseService, Depends(get_course_service)]
ContentServiceDep = Annotated[ContentService, Depends(get_content_service)]
SubmissionServiceDep = Annotated[SubmissionService, Depends(get_submission_service)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
ActorDep = Annotated[Actor, Depends(current_actor)]
MutationActorDep = Annotated[Actor, Depends(mutation_actor)]
VersionDep = Annotated[int, Depends(expected_version)]
