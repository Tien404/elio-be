from fastapi.testclient import TestClient

from app.core.security import verify_password
from app.infrastructure.db.repositories.identity_repository import IdentityRepository
from app.infrastructure.db.sql import Sql
from scripts.seed import PASSWORD, _seed_accounts, seed
from tests.helpers import bootstrap_admin, create_user, login, temp_password


def test_admin_issued_password_is_usable_and_not_exposed_by_reads(api):
    admin = bootstrap_admin(api)
    response = admin.post(
        "/api/v1/admin/accounts",
        json={
            "email": "issued@elio.test",
            "displayName": "Issued",
            "role": "STUDENT",
            "canCreateCourse": False,
        },
    )
    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    password = body["temporaryPassword"]
    account_id = body["account"]["id"]
    assert password == temp_password(api, account_id)
    student = login(api, "issued@elio.test", password)
    assert student.body["restricted"] is True
    assert "temporaryPassword" not in admin.get("/api/v1/admin/accounts").text
    assert "temporaryPassword" not in admin.get("/api/v1/me").json()
    assert password not in admin.get("/api/v1/admin/audit-entries").text
    reset = admin.post(
        f"/api/v1/admin/accounts/{account_id}/password-reset", json={"reason": "Lost password"}
    )
    assert reset.headers["cache-control"] == "no-store"
    assert reset.json()["temporaryPassword"] != password
    assert student.get("/api/v1/me").status_code == 401
    assert login(api, "issued@elio.test", reset.json()["temporaryPassword"]).body["restricted"]
    assert (
        TestClient(api.app)
        .post("/api/v1/auth/sessions", json={"email": "issued@elio.test", "password": password})
        .status_code
        == 401
    )


def test_non_admin_cannot_issue_temporary_password(api):
    admin = bootstrap_admin(api)
    student = create_user(api, admin, "student@elio.test")
    response = student.post(
        f"/api/v1/admin/accounts/{admin.account_id}/password-reset",
        json={"reason": "Not permitted"},
    )
    assert response.status_code == 403
    assert "temporaryPassword" not in response.json()


def test_demo_seed_migrates_identity_and_preserves_regular_password_policy(api):
    admin = bootstrap_admin(api, email="admin@elio.local")
    teacher = create_user(api, admin, "teacher@elio.local", "INSTRUCTOR", can_create_course=True)
    db = api.app.state.database
    with db.transaction() as connection:
        accounts = _seed_accounts(Sql(connection), reset_demo_credentials=True)
        assert accounts["ADMIN"] == admin.account_id
        assert accounts["INSTRUCTOR"] == teacher.account_id
    for email in [
        "admin@gmail.com",
        "teacher@gmail.com",
        "student@gmail.com",
        "teacher2@gmail.com",
        "student2@gmail.com",
    ]:
        assert not login(api, email, PASSWORD).body["restricted"]
    assert admin.get("/api/v1/me").status_code == 401
    assert teacher.get("/api/v1/me").status_code == 401
    with db.transaction() as connection:
        sql = Sql(connection)
        count = sql.scalar("SELECT COUNT(*) FROM users")
        _seed_accounts(sql)
        assert sql.scalar("SELECT COUNT(*) FROM users") == count
        assert IdentityRepository(sql).find_by_email("teacher@elio.local") is None
        assert verify_password(
            PASSWORD, IdentityRepository(sql).find_by_email("teacher@gmail.com")["password_hash"]
        )
    current = login(api, "student@gmail.com", PASSWORD)
    assert (
        current.put(
            "/api/v1/me/password", json={"currentPassword": PASSWORD, "newPassword": "11111111"}
        ).status_code
        == 400
    )
    # The public seed entrypoint must refuse the real test database before writes.
    import pytest

    with pytest.raises(RuntimeError, match="development"):
        seed(db, reset_demo_credentials=True)
