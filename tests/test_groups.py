"""Group assignments: forming groups, handing in for the group, grading the group."""

from app.infrastructure.db.sql import Sql
from scripts.migrate import apply_migrations
from tests.helpers import class_with_student, create_user
from tests.test_grading import _enroll_outsider, _grade, _page, _release
from tests.test_submissions import _box, _submit, _upload


def _group_box(c, size=2, **extra):
    return _box(c, mode="GROUP", maxGroupSize=size, **extra)


def test_upgrade_repairs_missing_group_size_without_hiding_unsubmitted_work(api, database):
    c = class_with_student(api)
    legacy = _group_box(c)
    empty = _group_box(c)
    configured = _group_box(c, size=2)
    _create(c.student, legacy, "Existing team")
    with database.transaction() as connection:
        sql = Sql(connection)
        sql.execute(
            """ALTER TABLE assignments DROP CHECK CK_assignments_group_size,
            ADD CONSTRAINT CK_assignments_group_size CHECK (
                (is_group_work = 0 AND max_group_size IS NULL)
                OR (is_group_work = 1 AND max_group_size BETWEEN 1 AND 20))"""
        )
        sql.execute(
            "UPDATE assignments SET max_group_size=NULL WHERE activity_id IN (%s,%s)",
            legacy["id"],
            empty["id"],
        )
        sql.execute("DELETE FROM schema_migrations WHERE migration_id='013_required_group_size'")
    try:
        apply_migrations(database)
        apply_migrations(database)
        for box in (legacy, empty):
            for user in (c.student, c.prof):
                assert _groups(user, box)["maxGroupSize"] == 4
            response = c.student.get(f"/api/v1/assignments/{box['id']}/submissions/me")
            assert response.status_code == 404 and response.json()["code"] == "NOT_SUBMITTED"
        assert _groups(c.student, legacy)["items"][0]["maxSize"] == 4
        assert _groups(c.student, configured)["maxGroupSize"] == 2
        import pytest

        with pytest.raises(Exception, match="CK_assignments_group_size"):
            with database.transaction() as connection:
                Sql(connection).execute(
                    "UPDATE assignments SET max_group_size=NULL WHERE activity_id=%s",
                    legacy["id"],
                )
    finally:
        apply_migrations(database)


def _groups(user, box):
    response = user.get(f"/api/v1/assignments/{box['id']}/groups")
    assert response.status_code == 200, response.text
    return response.json()


def _create(user, box, name, **extra):
    return user.post(f"/api/v1/assignments/{box['id']}/groups", json={"name": name, **extra})


def _third_student(api, c):
    """A third enrolled student (Tri)."""
    tri = create_user(api, c.admin, "tri@elio.test", "STUDENT", name="Tri")
    course_id = c.prof.get(f"/api/v1/offerings/{c.offering_id}").json()["courseId"]
    request = tri.post(f"/api/v1/courses/{course_id}/registrations").json()
    c.admin.post(f"/api/v1/admin/registrations/{request['id']}/decision", json={"approve": True})
    c.prof.post(f"/api/v1/offerings/{c.offering_id}/enrollments", json={"email": "tri@elio.test"})
    return tri


def test_students_form_a_group_and_any_member_hands_in(api):
    c = class_with_student(api)
    _enroll_outsider(c)
    tri = _third_student(api, c)
    box = _group_box(c, size=2)
    assert box["mode"] == "GROUP" and box["maxGroupSize"] == 2

    created = _create(c.student, box, "Team A")
    assert created.status_code == 201, created.text
    group = created.json()
    assert [m["displayName"] for m in group["members"]] == ["Stu"] and group["maxSize"] == 2

    listed = _groups(c.outsider, box)
    assert listed["myGroupId"] is None and [g["name"] for g in listed["items"]] == ["Team A"]
    joined = c.outsider.post(f"/api/v1/groups/{group['id']}/membership")
    assert joined.status_code == 200 and joined.json()["size"] == 2
    full = tri.post(f"/api/v1/groups/{group['id']}/membership")
    assert full.status_code == 409 and full.json()["code"] == "GROUP_NOT_JOINABLE"

    # stu hands in for the group; out sees the same submission and may resubmit
    file_id = _upload(c.student, c, box["id"]).json()["id"]
    first = _submit(c.student, box["id"], [file_id])
    assert first.status_code == 201, first.text
    submission = first.json()
    assert submission["subjectType"] == "GROUP" and submission["subjectId"] == group["id"]
    assert sorted(submission["recipientStudentIds"]) == sorted(
        [c.student.account_id, c.outsider.account_id]
    )
    mine = c.outsider.get(f"/api/v1/assignments/{box['id']}/submissions/me").json()
    assert mine["id"] == submission["id"]
    assert c.outsider.get(f"/api/v1/files/{file_id}/content").status_code == 200  # group mate
    assert tri.get(f"/api/v1/files/{file_id}/content").status_code == 404
    newer = _upload(c.outsider, c, box["id"], data=b"v2").json()["id"]
    assert _submit(c.outsider, box["id"], [newer], expected=1).json()["version"] == 2

    # submitted: members are fixed
    assert _groups(c.student, box)["items"][0]["locked"] is True
    leave = c.outsider.delete(f"/api/v1/groups/{group['id']}/membership")
    assert leave.status_code == 409 and leave.json()["code"] == "GROUP_NOT_LEAVABLE"

    # one grade for the group, shown to every member
    _grade(c.prof, submission["id"], score=9)
    _release(c.prof, box["id"])
    for student in (c.student, c.outsider):
        assert _page(student, c, student.account_id).json()["items"][0]["grade"] == 9
        events = [n["eventType"] for n in student.get("/api/v1/me/notifications").json()["items"]]
        assert "GRADES_RELEASED" in events
    assert _page(tri, c, tri.account_id).json()["items"][0]["grade"] is None


def test_group_rules(api):
    c = class_with_student(api)
    _enroll_outsider(c)
    box = _group_box(c, size=1)
    alone = _box(c, title="Solo work")

    no_group = _upload(c.student, c, box["id"])
    assert no_group.status_code == 409 and no_group.json()["code"] == "NO_GROUP"
    not_group = c.student.get(f"/api/v1/assignments/{alone['id']}/groups")
    assert not_group.status_code == 409 and not_group.json()["code"] == "NOT_GROUP_WORK"

    group = _create(c.student, box, "Solo").json()
    second = _create(c.student, box, "Another")
    assert second.status_code == 409 and second.json()["code"] == "ALREADY_IN_GROUP"
    taken = _create(c.outsider, box, "Solo")
    assert taken.status_code == 409 and taken.json()["code"] == "GROUP_NAME_TAKEN"
    assert c.outsider.post(f"/api/v1/groups/{group['id']}/membership").status_code == 409  # full

    left = c.student.delete(f"/api/v1/groups/{group['id']}/membership")
    assert left.status_code == 204
    assert _groups(c.student, box)["items"] == []  # the emptied group is gone
    assert _create(c.student, box, "x", memberIds=[c.outsider.account_id]).status_code == 400


def test_professor_makes_groups(api):
    c = class_with_student(api)
    _enroll_outsider(c)
    box = _group_box(c, size=2)
    both = [c.student.account_id, c.outsider.account_id]
    made = _create(c.prof, box, "Team P", memberIds=both)
    assert made.status_code == 201, made.text
    assert made.json()["size"] == 2

    assert _create(c.prof, box, "Empty").json()["size"] == 0  # filled in later
    clash = _create(c.prof, box, "Team Q", memberIds=[c.student.account_id])
    assert clash.status_code == 409 and clash.json()["code"] == "ALREADY_IN_GROUP"
    big = _create(c.prof, box, "Big", memberIds=[*both, c.prof.account_id])
    assert big.status_code == 422 and big.json()["code"] == "GROUP_TOO_LARGE"
    outsider = _create(c.prof, box, "Odd", memberIds=[c.prof.account_id])
    assert outsider.status_code == 422 and outsider.json()["code"] == "STUDENT_NOT_FOUND"

    url = f"/api/v1/groups/{made.json()['id']}"
    edited = c.prof.patch(url, json={"name": "Team Prime", "memberIds": [c.student.account_id]})
    assert edited.status_code == 200, edited.text
    assert edited.json()["name"] == "Team Prime" and edited.json()["size"] == 1
    assert c.student.patch(url, json={"name": "Mine"}).status_code == 403
    assert c.prof.post(f"{url}/membership").status_code == 403


def test_missing_work_marks_the_whole_group(api):
    c = class_with_student(api)
    _enroll_outsider(c)
    box = _group_box(c, size=2)
    _create(c.prof, box, "Team", memberIds=[c.student.account_id, c.outsider.account_id])
    from tests.test_main_adaptation import close_assignment

    close_assignment(api, box["id"])
    marked = c.prof.post(
        f"/api/v1/assignments/{box['id']}/missing-work-decisions",
        json={
            "studentId": c.student.account_id,
            "specialMark": "ABSENT",
            "zeroReason": "No submission",
        },
    )
    assert marked.status_code == 200, marked.text
    for student in (c.student, c.outsider):
        row = _page(c.prof, c, student.account_id).json()["items"][0]
        assert row["specialCode"] == 11
    assert _groups(c.prof, box)["items"][0]["locked"] is True


def test_group_mode_needs_a_size(api):
    c = class_with_student(api)
    url = f"/api/v1/offerings/{c.offering_id}/assignments"
    topic = c.prof.post(f"/api/v1/offerings/{c.offering_id}/topics", json={"title": "W"}).json()
    base = {
        "title": "x",
        "topicId": topic["id"],
        "openAt": "2030-01-01T00:00:00Z",
        "dueAt": "2030-01-02T00:00:00Z",
        "cutoffAt": "2030-01-03T00:00:00Z",
        "maxScore": 10,
        "status": "DRAFT",
    }
    assert c.prof.post(url, json={**base, "mode": "GROUP"}).status_code == 400
    assert c.prof.post(url, json={**base, "maxGroupSize": 3}).status_code == 400
