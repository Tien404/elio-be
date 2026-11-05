from fastapi import APIRouter

from app.services.auth_service import AuthService

router = APIRouter(tags=["identity"], responses={400: {"description": "Invalid request"}})


@router.post("/auth/sessions", operation_id="createSession", status_code=501)
def create_session():
    return AuthService().login()


@router.delete("/auth/session", operation_id="deleteCurrentSession", status_code=501)
def delete_current_session():
    return AuthService().logout()


@router.get("/me", operation_id="getMe", status_code=501)
def get_me():
    return AuthService().get_me()


@router.patch("/me", operation_id="updateMe", status_code=501)
def update_me():
    return AuthService().update_me()


@router.put("/me/password", operation_id="changePassword", status_code=501)
def change_password():
    return AuthService().change_password()
