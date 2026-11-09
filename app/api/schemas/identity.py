from typing import Annotated, Literal

from pydantic import Field

from app.api.schemas.common import (
    Email,
    Id,
    Instant,
    PageMeta,
    Reason,
    RequestModel,
    ResponseModel,
    Version,
)

Role = Literal["STUDENT", "INSTRUCTOR", "ADMIN"]
AccountStatus = Literal["ACTIVE", "LOCKED"]
DisplayName = Annotated[str, Field(min_length=1, max_length=120)]
Password = Annotated[str, Field(min_length=1, max_length=1024)]


class AccountSummary(ResponseModel):
    id: Id
    displayName: str
    status: AccountStatus
    role: Role
    mustChangePassword: bool


class SessionView(ResponseModel):
    account: AccountSummary
    csrfToken: str
    absoluteExpiresAt: Instant
    restricted: bool


class MeView(ResponseModel):
    account: AccountSummary
    email: str
    canCreateCourse: bool
    version: Version


class AccountPage(PageMeta):
    items: list[MeView]


class LoginRequest(RequestModel):
    email: Email
    password: Password


class UpdateProfileRequest(RequestModel):
    displayName: DisplayName


class ChangePasswordRequest(RequestModel):
    currentPassword: Password
    newPassword: Annotated[str, Field(min_length=12, max_length=1024)]


class SignUpRequest(RequestModel):
    """Public student registration."""

    email: Email
    displayName: DisplayName
    password: Annotated[str, Field(min_length=12, max_length=1024)]


class CreateAccountRequest(RequestModel):
    email: Email
    displayName: DisplayName
    canCreateCourse: bool
    role: Role


class AdminAccountUpdateRequest(RequestModel):
    status: AccountStatus | None = None
    canCreateCourse: bool | None = None
    reason: Reason


class ResetPasswordRequest(RequestModel):
    reason: Reason


class IdentityView(ResponseModel):
    me: MeView
    session: SessionView
