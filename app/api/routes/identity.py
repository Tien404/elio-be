from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.api.dependencies import (
    ActorDep,
    AuthServiceDep,
    MutationActorDep,
    SettingsDep,
    VersionDep,
    clear_session_cookie,
    mutation_session_allow_restricted,
    set_etag,
    set_session_cookie,
)
from app.api.schemas.common import ActionResult
from app.api.schemas.identity import (
    ChangePasswordRequest,
    LoginRequest,
    MeView,
    SessionView,
    UpdateProfileRequest,
)
from app.domain.context import SessionContext

router = APIRouter(tags=["identity"], responses={400: {"description": "Invalid request"}})

RestrictedMutation = Annotated[SessionContext, Depends(mutation_session_allow_restricted)]


@router.post(
    "/auth/sessions",
    operation_id="createSession",
    status_code=201,
    response_model=SessionView,
    responses={401: {"description": "INVALID_CREDENTIALS"}},
)
def create_session(
    body: LoginRequest, response: Response, service: AuthServiceDep, settings: SettingsDep
):
    issued = service.login(email=body.email, password=body.password)
    set_session_cookie(response, settings, issued.token, issued.view["absoluteExpiresAt"])
    response.headers["Cache-Control"] = "no-store"
    return issued.view


@router.delete("/auth/session", operation_id="deleteCurrentSession", status_code=204)
def delete_current_session(
    session: RestrictedMutation, service: AuthServiceDep, settings: SettingsDep
):
    service.logout(session=session)
    response = Response(status_code=204)
    clear_session_cookie(response, settings)
    return response


@router.get("/me", operation_id="getMe", response_model=MeView)
def get_me(actor: ActorDep, response: Response, service: AuthServiceDep):
    view = service.get_me(actor=actor)
    set_etag(response, view["version"])
    return view


@router.patch(
    "/me",
    operation_id="updateMe",
    response_model=MeView,
    responses={412: {"description": "VERSION_CONFLICT"}},
)
def update_me(
    body: UpdateProfileRequest,
    actor: MutationActorDep,
    version: VersionDep,
    response: Response,
    service: AuthServiceDep,
):
    view = service.update_me(actor=actor, display_name=body.displayName, expected_version=version)
    set_etag(response, view["version"])
    return view


@router.put("/me/password", operation_id="changePassword", response_model=ActionResult)
def change_password(
    body: ChangePasswordRequest,
    session: RestrictedMutation,
    response: Response,
    service: AuthServiceDep,
    settings: SettingsDep,
):
    result = service.change_password(
        actor=session.actor,
        current_password=body.currentPassword,
        new_password=body.newPassword,
    )
    # Every session (this one included) is revoked: the client must sign in again.
    clear_session_cookie(response, settings)
    return result
