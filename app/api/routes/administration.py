from fastapi import APIRouter, Path

from app.services.auth_service import AuthService

router = APIRouter(tags=["administration"], responses={400: {"description": "Invalid request"}})


@router.get("/admin/accounts", operation_id="adminListAccounts", status_code=501)
def admin_list_accounts():
    return AuthService().admin_list_accounts()


@router.post("/admin/accounts", operation_id="adminCreateAccount", status_code=501)
def admin_create_account():
    return AuthService().admin_create_account()


@router.patch("/admin/accounts/{accountId}", operation_id="adminUpdateAccount", status_code=501)
def admin_update_account(accountId: int = Path(ge=1, le=2147483647)):
    return AuthService().admin_update_account(account_id=accountId)


@router.get("/admin/offerings", operation_id="adminListCourses", status_code=501)
def admin_list_courses():
    return AuthService().admin_list_courses()


@router.get("/admin/audit-entries", operation_id="adminListAuditEntries", status_code=501)
def admin_list_audit_entries():
    return AuthService().admin_list_audit_entries()


@router.post(
    "/admin/accounts/{accountId}/password-reset", operation_id="adminResetPassword", status_code=501
)
def admin_reset_password(accountId: int = Path(ge=1, le=2147483647)):
    return AuthService().admin_reset_password(account_id=accountId)
