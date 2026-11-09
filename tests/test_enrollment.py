from fastapi.testclient import TestClient

from tests.helpers import bootstrap_admin, create_user

SEARCH = "/api/v1/courses"


def _add_course(admin, name, faculty="CS", year=1, degree="UNDERGRADUATE"):
    body = {
        "facultyCode": faculty,
        "yearLevel": year,
        "degreeLevel": degree,
        "courseName": name,
        "credits": 3,
    }
    response = admin.post("/api/v1/admin/courses", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _codes(response):
    assert response.status_code == 200, response.text
    return [item["courseCode"] for item in response.json()["items"]]


def _catalog(admin):
    _add_course(admin, "Intro to Programming")  # CS1001
    _add_course(admin, "Discrete Math")  # CS1002
    _add_course(admin, "Advanced Programming", year=2)  # CS2001
    _add_course(admin, "Lập trình Python", faculty="IT")  # IT1001


def test_search_by_code_prefix_or_name(api):
    admin = bootstrap_admin(api)
    student = create_user(api, admin, "stu@elio.test", "STUDENT")
    _catalog(admin)

    assert _codes(student.get(SEARCH)) == ["CS1001", "CS1002", "CS2001", "IT1001"]
    # code pattern -> code prefix (case-insensitive)
    assert _codes(student.get(SEARCH, params={"q": "cs10"})) == ["CS1001", "CS1002"]
    assert _codes(student.get(SEARCH, params={"q": "CS2001"})) == ["CS2001"]
    # name pattern -> name contains
    assert _codes(student.get(SEARCH, params={"q": "programming"})) == ["CS1001", "CS2001"]
    assert _codes(student.get(SEARCH, params={"q": "lập trình"})) == ["IT1001"]
    assert _codes(student.get(SEARCH, params={"q": "math_"})) == []  # _ is literal, no wildcard

    page = student.get(SEARCH, params={"pageSize": 3, "page": 2}).json()
    assert page["totalItems"] == 4 and page["totalPages"] == 2
    assert [item["courseCode"] for item in page["items"]] == ["IT1001"]


def test_search_rejects_input_matching_neither_pattern(api):
    admin = bootstrap_admin(api)
    for q in ("x", "drop table;", "<script>"):
        response = admin.get(SEARCH, params={"q": q})
        assert response.status_code == 400, q
        assert response.json()["code"] == "INVALID_SEARCH"
    assert TestClient(api.app).get(SEARCH).status_code == 401


def test_student_requests_a_course_once(api):
    admin = bootstrap_admin(api)
    student = create_user(api, admin, "stu@elio.test", "STUDENT")
    course = _add_course(admin, "Intro to Programming")
    url = f"/api/v1/courses/{course['id']}/registrations"

    created = student.post(url)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "PENDING" and body["decidedAt"] is None
    assert body["course"]["courseCode"] == "CS1001"

    again = student.post(url)
    assert again.status_code == 409 and again.json()["code"] == "ALREADY_REQUESTED"

    assert student.post("/api/v1/courses/999999/registrations").status_code == 404
    assert student.client.post(url).json()["code"] == "CSRF_REJECTED"


def test_only_students_request_courses(api):
    admin = bootstrap_admin(api)
    prof = create_user(api, admin, "prof@elio.test", "INSTRUCTOR")
    course = _add_course(admin, "Intro to Programming")
    url = f"/api/v1/courses/{course['id']}/registrations"
    for user in (admin, prof):
        response = user.post(url)
        assert response.status_code == 403 and response.json()["code"] == "FORBIDDEN"
