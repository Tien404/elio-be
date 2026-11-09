"""MVP step 2: CourseService.createOffering (POST /offerings)."""

from tests.helpers import bootstrap_admin, create_user

URL = "/api/v1/offerings"


def _course(admin, name="Intro to Programming"):
    body = {
        "facultyCode": "CS",
        "yearLevel": 1,
        "degreeLevel": "UNDERGRADUATE",
        "courseName": name,
        "credits": 3,
    }
    response = admin.post("/api/v1/admin/courses", json=body)
    assert response.status_code == 201, response.text
    return response.json()["courseCode"]


def test_admin_creates_class_and_names_the_professor(api):
    admin = bootstrap_admin(api)
    prof = create_user(api, admin, "prof@elio.test", "INSTRUCTOR")
    code = _course(admin)

    body = {
        "courseCode": code,
        "semester": "2026-1",
        "sectionCode": "01",
        "title": "CS1001 Morning",
    }
    first = admin.post(URL, json={**body, "instructorEmail": "PROF@elio.test"})
    assert first.status_code == 201, first.text
    view = first.json()
    assert view["courseCode"] == "CS1001" and view["sectionCode"] == "01"
    assert view["status"] == "DRAFT" and view["version"] == 1
    assert first.headers["location"] == f"/api/v1/offerings/{view['id']}"

    # sections count per course + semester
    second = admin.post(
        URL, json={**body, "sectionCode": "02", "instructorEmail": "prof@elio.test"}
    )
    assert second.json()["sectionCode"] == "02"
    other_term = admin.post(
        URL,
        json={
            **body,
            "semester": "2026-2",
            "sectionCode": "01",
            "instructorEmail": "prof@elio.test",
        },
    )
    assert other_term.json()["sectionCode"] == "01"
    assert prof.account_id  # professor exists; roster checks come with getRoster


def test_admin_must_name_an_active_instructor(api):
    admin = bootstrap_admin(api)
    create_user(api, admin, "stu@elio.test", "STUDENT")
    code = _course(admin)
    body = {"courseCode": code, "semester": "2026-1", "sectionCode": "01", "title": "T"}

    missing = admin.post(URL, json=body)
    assert missing.status_code == 400
    for email in ("nobody@elio.test", "stu@elio.test", "admin@elio.test"):
        response = admin.post(URL, json={**body, "instructorEmail": email})
        assert response.status_code == 422, email
        assert response.json()["code"] == "INSTRUCTOR_NOT_FOUND"


def test_flagged_instructor_creates_own_class(api):
    admin = bootstrap_admin(api)
    prof = create_user(api, admin, "prof@elio.test", "INSTRUCTOR", can_create_course=True)
    create_user(api, admin, "other@elio.test", "INSTRUCTOR")
    code = _course(admin)
    body = {
        "courseCode": code.lower(),
        "semester": "2026-1",
        "sectionCode": "01",
        "title": "My class",
    }

    own = prof.post(URL, json=body)
    assert own.status_code == 201, own.text
    assert own.json()["courseCode"] == "CS1001"

    naming_other = prof.post(URL, json={**body, "instructorEmail": "other@elio.test"})
    assert naming_other.status_code == 400


def test_unflagged_instructor_and_students_cannot_create_classes(api):
    admin = bootstrap_admin(api)
    prof = create_user(api, admin, "prof@elio.test", "INSTRUCTOR")
    student = create_user(api, admin, "stu@elio.test", "STUDENT")
    code = _course(admin)
    body = {"courseCode": code, "semester": "2026-1", "sectionCode": "01", "title": "T"}
    for user in (prof, student):
        response = user.post(URL, json=body)
        assert response.status_code == 403 and response.json()["code"] == "FORBIDDEN"


def test_unknown_course_is_404(api):
    admin = bootstrap_admin(api)
    create_user(api, admin, "prof@elio.test", "INSTRUCTOR")
    body = {
        "courseCode": "CS9999",
        "semester": "2026-1",
        "sectionCode": "01",
        "title": "T",
        "instructorEmail": "prof@elio.test",
    }
    assert admin.post(URL, json=body).status_code == 404
