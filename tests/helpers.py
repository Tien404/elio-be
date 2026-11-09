"""Small helpers for API integration tests."""

from dataclasses import dataclass, field

from fastapi.testclient import TestClient

from app.services.auth_service import AuthService

ADMIN_PASSWORD = "admin-password-123"
DEFAULT_PASSWORD = "user-password-12345"


@dataclass
class Session:
    """A logged-in client: its own cookie jar + CSRF token."""

    client: TestClient
    csrf: str
    account_id: int
    body: dict = field(default_factory=dict)

    def headers(self, version: int | None = None) -> dict[str, str]:
        result = {"X-CSRF-Token": self.csrf}
        if version is not None:
            result["If-Match"] = f'"{version}"'
        return result

    def get(self, url, **kw):
        return self.client.get(url, **kw)

    def post(self, url, json=None, version=None, **kw):
        return self.client.post(url, json=json, headers=self.headers(version), **kw)

    def patch(self, url, json=None, version=None, **kw):
        return self.client.patch(url, json=json, headers=self.headers(version), **kw)

    def put(self, url, json=None, version=None, **kw):
        return self.client.put(url, json=json, headers=self.headers(version), **kw)

    def delete(self, url, version=None, **kw):
        return self.client.request("DELETE", url, headers=self.headers(version), **kw)


def login(api: TestClient, email: str, password: str) -> Session:
    client = TestClient(api.app)  # separate cookie jar per user
    response = client.post("/api/v1/auth/sessions", json={"email": email, "password": password})
    assert response.status_code == 201, response.text
    body = response.json()
    return Session(
        client=client, csrf=body["csrfToken"], account_id=body["account"]["id"], body=body
    )


def bootstrap_admin(api: TestClient, email: str = "admin@elio.test") -> Session:
    state = api.app.state
    AuthService(state.database, state.settings).bootstrap_admin(
        email=email, display_name="Admin", password=ADMIN_PASSWORD
    )
    return login(api, email, ADMIN_PASSWORD)


def temp_password(api: TestClient, account_id: int) -> str:
    outbox = api.app.state.settings.credential_outbox_dir / f"{account_id}.txt"
    for line in outbox.read_text(encoding="utf-8").splitlines():
        if line.startswith("temporary_password: "):
            return line.split(": ", 1)[1]
    raise AssertionError("no temporary password delivered")


def create_user(
    api: TestClient,
    admin: Session,
    email: str,
    role: str = "STUDENT",
    *,
    can_create_course: bool = False,
    name: str | None = None,
    password: str = DEFAULT_PASSWORD,
) -> Session:
    """Admin provisions the account, the user signs in and replaces the temporary password."""
    response = admin.post(
        "/api/v1/admin/accounts",
        json={
            "email": email,
            "displayName": name or email.split("@")[0],
            "role": role,
            "canCreateCourse": can_create_course,
        },
    )
    assert response.status_code == 201, response.text
    account_id = response.json()["account"]["id"]
    first = login(api, email, temp_password(api, account_id))
    changed = first.put(
        "/api/v1/me/password",
        json={"currentPassword": temp_password(api, account_id), "newPassword": password},
    )
    assert changed.status_code == 200, changed.text
    return login(api, email, password)


@dataclass
class ClassSetup:
    admin: Session
    prof: Session
    student: Session
    outsider: Session
    offering_id: int


def class_with_student(api: TestClient) -> ClassSetup:
    """Course CS1001, one class taught by prof@, stu@ enrolled, out@ (student) not enrolled."""
    admin = bootstrap_admin(api)
    prof = create_user(api, admin, "prof@elio.test", "INSTRUCTOR", name="Prof")
    student = create_user(api, admin, "stu@elio.test", "STUDENT", name="Stu")
    outsider = create_user(api, admin, "out@elio.test", "STUDENT", name="Out")
    course = admin.post(
        "/api/v1/admin/courses",
        json={
            "facultyCode": "CS",
            "yearLevel": 1,
            "degreeLevel": "UNDERGRADUATE",
            "courseName": "Intro to Programming",
            "credits": 3,
        },
    ).json()
    offering = admin.post(
        "/api/v1/offerings",
        json={
            "courseCode": course["courseCode"],
            "semester": "2026-1",
            "sectionCode": "01",
            "title": "CS1001 Morning",
            "instructorEmail": "prof@elio.test",
        },
    ).json()
    published = prof.patch(
        f"/api/v1/offerings/{offering['id']}", json={"status": "OPEN"}, version=offering["version"]
    )
    assert published.status_code == 200, published.text
    request = student.post(f"/api/v1/courses/{course['id']}/registrations").json()
    admin.post(f"/api/v1/admin/registrations/{request['id']}/decision", json={"approve": True})
    enrolled = prof.post(
        f"/api/v1/offerings/{offering['id']}/enrollments", json={"email": "stu@elio.test"}
    )
    assert enrolled.status_code == 201, enrolled.text
    return ClassSetup(admin, prof, student, outsider, offering["id"])
