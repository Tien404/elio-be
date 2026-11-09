from tests.helpers import bootstrap_admin, create_user


def _setup(api):
    """Admin, professor, two students, course CS1001 and one class taught by the professor."""
    admin = bootstrap_admin(api)
    prof = create_user(api, admin, "prof@elio.test", "INSTRUCTOR", name="Prof")
    ann = create_user(api, admin, "ann@elio.test", "STUDENT", name="Ann")
    bob = create_user(api, admin, "bob@elio.test", "STUDENT", name="Bob")
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
            "courseCode": "CS1001",
            "semester": "2026-1",
            "sectionCode": "01",
            "title": "CS1001 Morning",
            "instructorEmail": "prof@elio.test",
        },
    ).json()
    opened = prof.patch(
        f"/api/v1/offerings/{offering['id']}", json={"status": "OPEN"}, version=offering["version"]
    )
    assert opened.status_code == 200, opened.text
    offering = opened.json()
    return admin, prof, ann, bob, course, offering


def _request(student, course):
    response = student.post(f"/api/v1/courses/{course['id']}/registrations")
    assert response.status_code == 201, response.text
    return response.json()


def _decide(admin, registration, approve):
    return admin.post(
        f"/api/v1/admin/registrations/{registration['id']}/decision", json={"approve": approve}
    )


def test_full_enrollment_flow(api):
    admin, prof, ann, bob, course, offering = _setup(api)
    oid = offering["id"]
    ann_request, bob_request = _request(ann, course), _request(bob, course)

    # admin review queue
    queue = admin.get("/api/v1/admin/registrations", params={"status": "PENDING"}).json()
    assert queue["totalItems"] == 2
    assert [item["student"]["email"] for item in queue["items"]] == [
        "ann@elio.test",
        "bob@elio.test",
    ]
    approved = _decide(admin, ann_request, True)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPROVED" and approved.json()["decidedAt"]
    assert _decide(admin, bob_request, False).json()["status"] == "REJECTED"
    twice = _decide(admin, ann_request, False)
    assert twice.status_code == 409 and twice.json()["code"] == "REGISTRATION_ALREADY_DECIDED"

    # professor's waiting list shows only the approved student
    waiting = prof.get(f"/api/v1/offerings/{oid}/approved-students").json()["items"]
    assert [s["email"] for s in waiting] == ["ann@elio.test"]

    # Lead adds an existing student directly; students cannot add themselves by email.
    added = prof.post(f"/api/v1/offerings/{oid}/enrollments", json={"email": "ANN@elio.test"})
    assert added.status_code == 201, added.text
    assert added.json()["role"] == "STUDENT" and added.json()["account"]["displayName"] == "Ann"
    rejected = bob.post(f"/api/v1/offerings/{oid}/enrollments", json={"email": "bob@elio.test"})
    assert rejected.status_code == 403
    again = prof.post(f"/api/v1/offerings/{oid}/enrollments", json={"email": "ann@elio.test"})
    assert again.status_code == 409 and again.json()["code"] == "ALREADY_ENROLLED"
    assert prof.get(f"/api/v1/offerings/{oid}/approved-students").json()["items"] == []

    # my classes
    for user in (ann, prof, admin):
        classes = user.get("/api/v1/offerings").json()
        assert [c["id"] for c in classes["items"]] == [oid], user.body["account"]["role"]
    assert bob.get("/api/v1/offerings").json()["items"] == []

    # class page + roster (professor first)
    page = ann.get(f"/api/v1/offerings/{oid}")
    assert page.status_code == 200 and page.json()["courseCode"] == "CS1001"
    roster = ann.get(f"/api/v1/offerings/{oid}/memberships").json()
    assert [(m["account"]["displayName"], m["teachingRole"]) for m in roster["items"]] == [
        ("Prof", "LEAD"),
        ("Ann", None),
    ]
    # outsiders don't see the class at all
    assert bob.get(f"/api/v1/offerings/{oid}").status_code == 404
    assert bob.get(f"/api/v1/offerings/{oid}/memberships").status_code == 404
    candidates = prof.get(f"/api/v1/offerings/{oid}/enrollment-candidates").json()
    assert bob.account_id in [a["id"] for a in candidates["items"]]
    direct = prof.post(f"/api/v1/offerings/{oid}/enrollments", json={"accountId": bob.account_id})
    assert direct.status_code == 201, direct.text


def test_only_admin_reviews_and_only_the_class_professor_adds(api):
    admin, prof, ann, bob, course, offering = _setup(api)
    oid = offering["id"]
    other_prof = create_user(api, admin, "other@elio.test", "INSTRUCTOR")
    request = _request(ann, course)

    for user in (prof, ann):
        assert _decide(user, request, True).status_code == 403
        assert user.get("/api/v1/admin/registrations").status_code == 403
    _decide(admin, request, True)

    body = {"email": "ann@elio.test"}
    for user in (other_prof, ann, admin):
        response = user.post(f"/api/v1/offerings/{oid}/enrollments", json=body)
        assert response.status_code == 403, user.body["account"]["role"]
    assert other_prof.get(f"/api/v1/offerings/{oid}/approved-students").status_code == 403
    assert admin.get(f"/api/v1/offerings/{oid}/approved-students").status_code == 200

    unknown = prof.post(f"/api/v1/offerings/{oid}/enrollments", json={"email": "x@elio.test"})
    assert unknown.status_code == 422 and unknown.json()["code"] == "STUDENT_NOT_FOUND"
    assert prof.post("/api/v1/offerings/999999/enrollments", json=body).status_code == 404


def test_student_goes_into_only_one_class_per_course(api):
    admin, prof, ann, bob, course, offering = _setup(api)
    second = admin.post(
        "/api/v1/offerings",
        json={
            "courseCode": "CS1001",
            "semester": "2026-1",
            "sectionCode": "02",
            "title": "CS1001 Evening",
            "instructorEmail": "prof@elio.test",
        },
    ).json()
    opened = prof.patch(
        f"/api/v1/offerings/{second['id']}", json={"status": "OPEN"}, version=second["version"]
    )
    assert opened.status_code == 200, opened.text
    ok = prof.post(
        f"/api/v1/offerings/{offering['id']}/enrollments", json={"email": "ann@elio.test"}
    )
    assert ok.status_code == 201
    dup = prof.post(
        f"/api/v1/offerings/{second['id']}/enrollments", json={"email": "ann@elio.test"}
    )
    assert dup.status_code == 409 and dup.json()["code"] == "ALREADY_ENROLLED"
