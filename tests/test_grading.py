"""Manual grading: the professor fills grade boxes (drafts), releases them per assignment,
and students see the same grade report with released grades only."""

from tests.helpers import class_with_student
from tests.test_submissions import _box, _submit, _upload


def _submitted(c, **box_args):
    box = _box(c, **box_args)
    file_id = _upload(c.student, c, box["id"]).json()["id"]
    submission = _submit(c.student, box["id"], [file_id])
    assert submission.status_code == 201, submission.text
    return box, submission.json()["id"]


def _grade(user, submission_id, **body):
    response = user.get(f"/api/v1/submissions/{submission_id}/history")
    if response.status_code != 200:
        return user.post(
            f"/api/v1/submissions/{submission_id}/grade-record",
            json={"expectedSubmissionVersion": 1, "sourceVersionNo": 1, **body},
        )
    stream = response.json()
    submission = stream["submission"]
    from tests.test_main_adaptation import close_assignment

    close_assignment(user.client, submission["assignmentId"])
    payload = {
        "expectedSubmissionVersion": submission["version"],
        "sourceVersionNo": submission["currentVersion"]["versionNo"]
        if submission["currentVersion"]
        else None,
        **body,
    }
    if submission["status"] != "SUBMITTED":
        payload["zeroReason"] = "No work submitted"
    grade = stream["grade"]
    if grade:
        return user.post(
            f"/api/v1/grade-records/{grade['id']}/revisions",
            json={"reason": "Rechecked during test", **payload},
            version=grade["version"],
        )
    return user.post(f"/api/v1/submissions/{submission_id}/grade-record", json=payload)


def _page(user, c, student_id=None):
    student_id = student_id or c.student.account_id
    return user.get(f"/api/v1/offerings/{c.offering_id}/students/{student_id}/grades")


def _release(user, assignment_id):
    return user.put(f"/api/v1/assignments/{assignment_id}/grade-release")


def _enroll_outsider(c):
    """out@ joins the class too, as a second student."""
    course_id = c.prof.get(f"/api/v1/offerings/{c.offering_id}").json()["courseId"]
    request = c.outsider.post(f"/api/v1/courses/{course_id}/registrations").json()
    c.admin.post(f"/api/v1/admin/registrations/{request['id']}/decision", json={"approve": True})
    enrolled = c.prof.post(
        f"/api/v1/offerings/{c.offering_id}/enrollments", json={"email": "out@elio.test"}
    )
    assert enrolled.status_code == 201, enrolled.text


def test_draft_is_hidden_until_released(api):
    c = class_with_student(api)
    box, submission_id = _submitted(c)

    saved = _grade(c.prof, submission_id, score=8, feedback="Good work")
    assert saved.status_code == 200, saved.text
    item = saved.json()
    assert item["status"] == "DRAFT" and item["grade"] == 8 and item["percentage"] == 80
    assert item["rangeMin"] == 0 and item["rangeMax"] == 10 and item["feedback"] == "Good work"

    hidden = _page(c.student, c).json()["items"][0]
    assert hidden["status"] == "NOT_GRADED" and hidden["grade"] is None
    assert hidden["feedback"] is None and hidden["percentage"] is None

    released = _release(c.prof, box["id"])
    assert released.status_code == 200 and released.json()["released"] == 1
    shown = _page(c.student, c).json()["items"][0]
    assert shown["status"] == "RELEASED" and shown["grade"] == 8 and shown["percentage"] == 80
    assert shown["feedback"] == "Good work"
    assert _release(c.prof, box["id"]).json()["released"] == 0  # nothing new


def test_edit_after_release_stays_draft_until_next_release(api):
    c = class_with_student(api)
    box, submission_id = _submitted(c)
    _grade(c.prof, submission_id, score=8)
    _release(c.prof, box["id"])

    changed = _grade(c.prof, submission_id, score=9.5).json()
    assert changed["status"] == "DRAFT" and changed["grade"] == 9.5
    assert _page(c.student, c).json()["items"][0]["grade"] == 8  # old grade still shown
    assert _page(c.prof, c).json()["items"][0]["grade"] == 9.5  # professor sees the draft

    _release(c.prof, box["id"])
    assert _page(c.student, c).json()["items"][0]["grade"] == 9.5


def test_special_marks_count_as_zero(api):
    c = class_with_student(api)
    _enroll_outsider(c)
    box, submission_id = _submitted(c)

    from tests.test_main_adaptation import close_assignment

    close_assignment(api, box["id"])
    # out@ did not submit: 11 = absent
    absent = c.prof.post(
        f"/api/v1/assignments/{box['id']}/missing-work-decisions",
        json={
            "studentId": c.outsider.account_id,
            "specialMark": "ABSENT",
            "zeroReason": "No submission",
        },
    )
    assert absent.status_code == 200, absent.text
    item = absent.json()
    assert item["specialMark"] == "ABSENT" and item["specialCode"] == 11
    assert item["grade"] == 0 and item["percentage"] == 0 and item["submitted"] is False

    # a student who submitted can be banned (12), but not marked absent
    assert _grade(c.prof, submission_id, specialMark="ABSENT").status_code == 422
    banned = _grade(c.prof, submission_id, specialMark="BANNED").json()
    assert banned["specialCode"] == 12 and banned["grade"] == 0

    # the absent student's record takes a special mark, never a plain score
    container = item["submissionId"]
    no_work = _grade(c.prof, container, score=5)
    assert no_work.status_code == 422 and no_work.json()["code"] == "INVALID_GRADE"
    assert _grade(c.prof, container, specialMark="BANNED").json()["specialCode"] == 12


def test_grade_blocks_only_that_students_resubmission(api):
    c = class_with_student(api)
    _enroll_outsider(c)
    box = _box(c)
    from tests.test_main_adaptation import close_assignment

    close_assignment(api, box["id"])
    marked = c.prof.post(
        f"/api/v1/assignments/{box['id']}/missing-work-decisions",
        json={
            "studentId": c.student.account_id,
            "specialMark": "ABSENT",
            "zeroReason": "No submission by cutoff",
        },
    )
    assert marked.status_code == 200, marked.text
    assert _upload(c.student, c, box["id"]).status_code == 409
    assert _upload(c.outsider, c, box["id"]).status_code == 409


def test_course_total_and_contribution(api):
    c = class_with_student(api)
    first, first_sub = _submitted(c, title="Homework 1", weight=40)
    second, second_sub = _submitted(c, title="Homework 2", weight=60)
    _grade(c.prof, first_sub, score=5)
    report = _page(c.prof, c).json()
    assert report["courseCode"] == "CS1001" and report["student"]["displayName"] == "Stu"
    one, two = report["items"]
    assert one["weight"] == 40 and one["contribution"] == 20  # 5/10 of 40%
    assert two["weight"] == 60 and two["contribution"] is None and two["grade"] is None
    assert report["total"]["rangeMax"] == 10
    assert report["total"]["grade"] == 2
    assert report["total"]["final"] is False

    _grade(c.prof, second_sub, score=10)
    assert _page(c.prof, c).json()["total"]["grade"] == 8
    assert _page(c.prof, c).json()["total"]["percentage"] == 80

    for box in (first, second):
        _release(c.prof, box["id"])
    mine = c.student.get("/api/v1/me/grades").json()["items"]
    assert len(mine) == 1 and mine[0]["total"]["grade"] == 8


def test_invalid_grade_boxes(api):
    c = class_with_student(api)
    _, submission_id = _submitted(c)
    too_high = _grade(c.prof, submission_id, score=10.5)
    assert too_high.status_code == 422 and too_high.json()["code"] == "INVALID_GRADE"
    assert _grade(c.prof, submission_id, score=-1).status_code == 400
    assert _grade(c.prof, submission_id).status_code == 400  # neither
    assert _grade(c.prof, submission_id, score=5, specialMark="BANNED").status_code == 400
    assert _grade(c.prof, submission_id, score=1.234).status_code == 400  # 2 decimals max
    assert _grade(c.prof, 999999, score=5).status_code == 404


def test_who_can_grade_and_see(api):
    c = class_with_student(api)
    box, submission_id = _submitted(c)
    assert _grade(c.student, submission_id, score=10).status_code == 403
    assert _grade(c.outsider, submission_id, score=10).status_code == 404
    assert _grade(c.admin, submission_id, score=10).status_code == 404
    assert _release(c.student, box["id"]).status_code == 403

    assert _page(c.student, c, c.prof.account_id).status_code == 404  # only my own page
    assert _page(c.outsider, c).status_code == 404
    assert _page(c.prof, c, c.outsider.account_id).status_code == 404  # not in the class
    assert c.outsider.get("/api/v1/me/grades").json() == {"items": []}
