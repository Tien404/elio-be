"""Team MVP flow step 1: admin creates catalog courses with generated codes (CS1001...)."""

from tests.helpers import bootstrap_admin, create_user

URL = "/api/v1/admin/courses"


def _course(name="Intro to Programming", faculty="CS", year=1, degree="UNDERGRADUATE", **extra):
    return {
        "facultyCode": faculty,
        "yearLevel": year,
        "degreeLevel": degree,
        "courseName": name,
        "credits": 3,
        **extra,
    }


def test_admin_creates_courses_with_generated_codes(api):
    admin = bootstrap_admin(api)
    first = admin.post(URL, json=_course())
    assert first.status_code == 201, first.text
    assert first.json() == {
        "id": first.json()["id"],
        "courseCode": "CS1001",
        "courseName": "Intro to Programming",
        "credits": 3.0,
    }
    assert admin.post(URL, json=_course("Discrete Math")).json()["courseCode"] == "CS1002"
    # different year / degree / faculty start their own numbering; lower-case prefix is fine
    assert admin.post(URL, json=_course("Algorithms", year=2)).json()["courseCode"] == "CS2001"
    assert admin.post(URL, json=_course("ML", degree="MASTERS")).json()["courseCode"] == "CS1101"
    assert admin.post(URL, json=_course("Research", degree="PHD")).json()["courseCode"] == "CS1201"
    assert admin.post(URL, json=_course("Calculus", faculty="math")).json()["courseCode"] == (
        "MATH1001"
    )


def test_only_admin_can_create_courses(api):
    admin = bootstrap_admin(api)
    prof = create_user(api, admin, "prof@elio.test", "INSTRUCTOR", can_create_course=True)
    student = create_user(api, admin, "stu@elio.test", "STUDENT")
    for user in (prof, student):
        response = user.post(URL, json=_course())
        assert response.status_code == 403 and response.json()["code"] == "FORBIDDEN"
    no_csrf = admin.client.post(URL, json=_course())
    assert no_csrf.status_code == 403 and no_csrf.json()["code"] == "CSRF_REJECTED"


def test_course_input_is_validated(api):
    admin = bootstrap_admin(api)
    bad = [
        _course(faculty="C"),  # prefix 2-4 letters
        _course(faculty="CS1"),
        _course(year=0),
        _course(degree="BACHELOR"),
        _course(name=""),
        {**_course(), "credits": 0},
        {**_course(), "courseCode": "CS9999"},  # code is generated, not chosen
    ]
    for body in bad:
        assert admin.post(URL, json=body).status_code in (400, 422), body
    assert admin.post(URL, json=_course(name="   ")).status_code == 400
