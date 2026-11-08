"""B1 identity on real SQL Server: login, sessions, CSRF, /me, passwords, admin accounts."""

from fastapi.testclient import TestClient

from tests.helpers import (
    ADMIN_PASSWORD,
    DEFAULT_PASSWORD,
    bootstrap_admin,
    create_user,
    login,
    temp_password,
)


def test_login_sets_httponly_cookie_and_returns_session_view(api):
    admin = bootstrap_admin(api)
    assert admin.body["account"]["role"] == "ADMIN"
    assert admin.body["restricted"] is False
    assert len(admin.csrf) >= 32
    raw = TestClient(api.app).post(
        "/api/v1/auth/sessions", json={"email": "ADMIN@elio.test", "password": ADMIN_PASSWORD}
    )
    assert raw.status_code == 201  # email is case-insensitive
    cookie = raw.headers["set-cookie"].lower()
    assert "elio_session=" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    assert "elio_session" not in raw.text  # token only in the cookie


def test_bad_credentials_are_generic(api):
    bootstrap_admin(api)
    client = TestClient(api.app)
    wrong = client.post("/api/v1/auth/sessions", json={"email": "admin@elio.test", "password": "x"})
    unknown = client.post("/api/v1/auth/sessions", json={"email": "who@elio.test", "password": "x"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["code"] == unknown.json()["code"] == "INVALID_CREDENTIALS"
    assert wrong.json()["detail"] == unknown.json()["detail"]


def test_protected_routes_require_session(api):
    assert TestClient(api.app).get("/api/v1/me").json()["code"] == "UNAUTHENTICATED"


def test_get_and_update_me_with_etag_and_csrf(api):
    admin = bootstrap_admin(api)
    me = admin.get("/api/v1/me")
    assert me.status_code == 200 and me.headers["etag"] == '"1"'
    assert me.json()["email"] == "admin@elio.test"

    no_csrf = admin.client.patch(
        "/api/v1/me", json={"displayName": "New"}, headers={"If-Match": '"1"'}
    )
    assert no_csrf.status_code == 403 and no_csrf.json()["code"] == "CSRF_REJECTED"

    updated = admin.patch("/api/v1/me", json={"displayName": "Ada Admin"}, version=1)
    assert updated.status_code == 200
    assert updated.json()["account"]["displayName"] == "Ada Admin"
    assert updated.json()["version"] == 2 and updated.headers["etag"] == '"2"'

    stale = admin.patch("/api/v1/me", json={"displayName": "Old"}, version=1)
    assert stale.status_code == 412
    assert stale.json()["code"] == "VERSION_CONFLICT" and stale.json()["currentVersion"] == 2

    extra = admin.patch("/api/v1/me", json={"displayName": "X", "email": "x@y.z"}, version=2)
    assert extra.status_code == 400  # /me only edits displayName


def test_temporary_password_session_is_restricted_until_changed(api):
    admin = bootstrap_admin(api)
    created = admin.post(
        "/api/v1/admin/accounts",
        json={
            "email": "stu@elio.test",
            "displayName": "Stu",
            "role": "STUDENT",
            "canCreateCourse": False,
        },
    )
    assert created.status_code == 201
    assert created.json()["account"]["mustChangePassword"] is True
    account_id = created.json()["account"]["id"]
    temp = temp_password(api, account_id)
    assert temp not in created.text  # temporary password only goes to the delivery channel

    first = login(api, "stu@elio.test", temp)
    assert first.body["restricted"] is True
    blocked = first.get("/api/v1/me")
    assert blocked.status_code == 403 and blocked.json()["code"] == "PASSWORD_CHANGE_REQUIRED"

    weak = first.put("/api/v1/me/password", json={"currentPassword": temp, "newPassword": "short"})
    assert weak.status_code == 400

    changed = first.put(
        "/api/v1/me/password", json={"currentPassword": temp, "newPassword": DEFAULT_PASSWORD}
    )
    assert changed.status_code == 200
    assert changed.json() == {"status": "COMPLETED", "resourceId": account_id}
    # every session, including the current one, is revoked
    assert first.get("/api/v1/me").status_code == 401

    again = login(api, "stu@elio.test", DEFAULT_PASSWORD)
    assert again.body["restricted"] is False
    assert again.get("/api/v1/me").json()["account"]["mustChangePassword"] is False


def test_logout_revokes_only_current_session(api):
    admin = bootstrap_admin(api)
    other = login(api, "admin@elio.test", ADMIN_PASSWORD)
    assert admin.delete("/api/v1/auth/session").status_code == 204
    assert admin.get("/api/v1/me").status_code == 401
    assert other.get("/api/v1/me").status_code == 200


def test_admin_create_account_rules(api):
    admin = bootstrap_admin(api)
    teacher = create_user(api, admin, "t@elio.test", "INSTRUCTOR", can_create_course=True)
    assert teacher.get("/api/v1/me").json()["canCreateCourse"] is True

    duplicate = admin.post(
        "/api/v1/admin/accounts",
        json={
            "email": "T@ELIO.TEST",
            "displayName": "Dup",
            "role": "STUDENT",
            "canCreateCourse": False,
        },
    )
    assert duplicate.status_code == 409 and duplicate.json()["code"] == "EMAIL_TAKEN"

    bad_flag = admin.post(
        "/api/v1/admin/accounts",
        json={
            "email": "s@elio.test",
            "displayName": "S",
            "role": "STUDENT",
            "canCreateCourse": True,
        },
    )
    assert bad_flag.status_code == 400

    not_admin = teacher.post(
        "/api/v1/admin/accounts",
        json={
            "email": "x@elio.test",
            "displayName": "X",
            "role": "STUDENT",
            "canCreateCourse": False,
        },
    )
    assert not_admin.status_code == 403


def test_admin_lock_revokes_sessions_and_blocks_login(api):
    admin = bootstrap_admin(api)
    student = create_user(api, admin, "s@elio.test")
    account = admin.get("/api/v1/admin/accounts?q=s%40elio").json()["items"][0]

    locked = admin.patch(
        f"/api/v1/admin/accounts/{student.account_id}",
        json={"status": "LOCKED", "reason": "Graduated"},
        version=account["version"],
    )
    assert locked.status_code == 200 and locked.json()["account"]["status"] == "LOCKED"
    assert student.get("/api/v1/me").status_code == 401
    relogin = TestClient(api.app).post(
        "/api/v1/auth/sessions", json={"email": "s@elio.test", "password": DEFAULT_PASSWORD}
    )
    assert relogin.status_code == 401

    stale = admin.patch(
        f"/api/v1/admin/accounts/{student.account_id}",
        json={"status": "ACTIVE", "reason": "Oops"},
        version=account["version"],
    )
    assert stale.status_code == 412

    self_lock = admin.patch(
        f"/api/v1/admin/accounts/{admin.account_id}",
        json={"status": "LOCKED", "reason": "x"},
        version=1,
    )
    assert self_lock.status_code == 409


def test_admin_reset_password_issues_new_temp_and_revokes_sessions(api):
    admin = bootstrap_admin(api)
    student = create_user(api, admin, "s@elio.test")
    reset = admin.post(
        f"/api/v1/admin/accounts/{student.account_id}/password-reset", json={"reason": "Forgot"}
    )
    assert reset.status_code == 200
    assert student.get("/api/v1/me").status_code == 401
    fresh = login(api, "s@elio.test", temp_password(api, student.account_id))
    assert fresh.body["restricted"] is True


def test_admin_list_accounts_pages(api):
    admin = bootstrap_admin(api)
    for i in range(3):
        create_user(api, admin, f"s{i}@elio.test")
    page = admin.get("/api/v1/admin/accounts?pageSize=2&page=2").json()
    assert page["totalItems"] == 4 and page["totalPages"] == 2 and len(page["items"]) == 2
    students = admin.get("/api/v1/admin/accounts?q=s1").json()
    assert [item["email"] for item in students["items"]] == ["s1@elio.test"]


def test_cli_account_creation_logs_in_without_temporary_password(api):
    from app.core.errors import ApiError
    from app.services.auth_service import AuthService

    service = AuthService(api.app.state.database, api.app.state.settings)
    try:
        service.create_account_with_password(
            email="s@elio.test", display_name="S", role="STUDENT", password=DEFAULT_PASSWORD
        )
        raise AssertionError("must require an admin first")
    except ApiError as error:
        assert error.code == "NO_ADMIN"

    bootstrap_admin(api)
    prof_id = service.create_account_with_password(
        email="Prof@elio.test",
        display_name="Prof",
        role="INSTRUCTOR",
        password=DEFAULT_PASSWORD,
        can_create_course=True,
    )
    prof = login(api, "prof@elio.test", DEFAULT_PASSWORD)
    assert prof.account_id == prof_id and prof.body["restricted"] is False
    assert prof.get("/api/v1/me").json()["canCreateCourse"] is True
    try:
        service.create_account_with_password(
            email="PROF@elio.test", display_name="Dup", role="STUDENT", password=DEFAULT_PASSWORD
        )
        raise AssertionError("duplicate email accepted")
    except ApiError as error:
        assert error.code == "EMAIL_TAKEN"
