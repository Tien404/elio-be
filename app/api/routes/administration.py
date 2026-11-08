from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query, Response

from app.api.dependencies import (
    ActorDep,
    AuthServiceDep,
    CatalogServiceDep,
    MutationActorDep,
    VersionDep,
    set_etag,
)
from app.api.schemas.catalog import CatalogCourse, CreateCatalogCourseRequest
from app.api.schemas.common import ActionResult
from app.api.schemas.identity import (
    AccountPage,
    AdminAccountUpdateRequest,
    CreateAccountRequest,
    MeView,
    ResetPasswordRequest,
)

router = APIRouter(tags=["administration"], responses={400: {"description": "Invalid request"}})

AccountId = Annotated[int, Path(alias="accountId", ge=1, le=2147483647)]


@router.get("/admin/accounts", operation_id="adminListAccounts", response_model=AccountPage)
def admin_list_accounts(
    actor: ActorDep,
    service: AuthServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    pageSize: Annotated[int, Query(ge=1, le=100)] = 25,
    q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    status: Literal["ACTIVE", "LOCKED"] | None = None,
    canCreateCourse: bool | None = None,
):
    return service.admin_list_accounts(
        actor=actor,
        page=page,
        page_size=pageSize,
        q=q,
        status=status,
        can_create_course=canCreateCourse,
    )


@router.post(
    "/admin/accounts",
    operation_id="adminCreateAccount",
    status_code=201,
    response_model=MeView,
    responses={409: {"description": "EMAIL_TAKEN"}},
)
def admin_create_account(
    body: CreateAccountRequest, actor: MutationActorDep, response: Response, service: AuthServiceDep
):
    view = service.admin_create_account(
        actor=actor,
        email=body.email,
        display_name=body.displayName,
        role=body.role,
        can_create_course=body.canCreateCourse,
    )
    set_etag(response, view["version"])
    return view


@router.patch(
    "/admin/accounts/{accountId}",
    operation_id="adminUpdateAccount",
    response_model=MeView,
    responses={
        409: {"description": "LEAD_TRANSFER_REQUIRED"},
        412: {"description": "VERSION_CONFLICT"},
    },
)
def admin_update_account(
    account_id: AccountId,
    body: AdminAccountUpdateRequest,
    actor: MutationActorDep,
    version: VersionDep,
    response: Response,
    service: AuthServiceDep,
):
    view = service.admin_update_account(
        actor=actor,
        account_id=account_id,
        expected_version=version,
        reason=body.reason,
        status=body.status,
        can_create_course=body.canCreateCourse,
    )
    set_etag(response, view["version"])
    return view


@router.post(
    "/admin/courses",
    operation_id="adminCreateCatalogCourse",
    status_code=201,
    response_model=CatalogCourse,
    summary="Admin adds a catalog course; the course code (e.g. CS1001) is generated.",
    responses={409: {"description": "COURSE_CODE_EXHAUSTED"}},
)
def admin_create_catalog_course(
    body: CreateCatalogCourseRequest, actor: MutationActorDep, service: CatalogServiceDep
):
    return service.admin_create_course(
        actor=actor,
        faculty_code=body.facultyCode,
        year_level=body.yearLevel,
        degree_level=body.degreeLevel,
        course_name=body.courseName,
        credits=body.credits,
        description=body.description,
    )


@router.get("/admin/offerings", operation_id="adminListCourses", status_code=501)
def admin_list_courses(service: AuthServiceDep):
    return service.admin_list_courses()


@router.get("/admin/audit-entries", operation_id="adminListAuditEntries", status_code=501)
def admin_list_audit_entries(service: AuthServiceDep):
    return service.admin_list_audit_entries()


@router.post(
    "/admin/accounts/{accountId}/password-reset",
    operation_id="adminResetPassword",
    response_model=ActionResult,
)
def admin_reset_password(
    account_id: AccountId,
    body: ResetPasswordRequest,
    actor: MutationActorDep,
    service: AuthServiceDep,
):
    return service.admin_reset_password(actor=actor, account_id=account_id, reason=body.reason)
