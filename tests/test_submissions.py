"""MVP step 6+7: SubmissionService — submission boxes, file submissions, late flag."""

from datetime import UTC, datetime, timedelta

from app.services import submission_service
from tests.helpers import class_with_student


def _future(days=7):
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


def _box(c, status="PUBLISHED", title="Homework 1", **extra):
    topic = c.prof.post(f"/api/v1/offerings/{c.offering_id}/topics", json={"title": "Week 1"})
    response = c.prof.post(
        f"/api/v1/offerings/{c.offering_id}/assignments",
        json={
            "title": title,
            "topicId": topic.json()["id"],
            "openAt": _future(-1),
            "cutoffAt": extra.get("dueAt", _future(8)),
            "dueAt": _future(),
            "maxScore": 10,
            "status": status,
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _upload(user, c, assignment_id, data=b"my answer", name="answer.pdf"):
    return user.post(
        "/api/v1/files",
        params={
            "offeringId": c.offering_id,
            "purpose": "SUBMISSION",
            "assignmentId": assignment_id,
        },
        files={"file": (name, data, "application/pdf")},
    )


def _submit(user, assignment_id, file_ids, expected=0):
    return user.post(
        f"/api/v1/assignments/{assignment_id}/submissions",
        json={"expectedVersion": expected, "fileIds": file_ids},
    )


def test_box_is_hidden_until_published(api):
    c = class_with_student(api)
    box = _box(c, status="DRAFT")
    assert box["mode"] == "INDIVIDUAL" and box["cutoffAt"] is not None and box["maxScore"] == 10
    boxes = f"/api/v1/offerings/{c.offering_id}/assignments"
    assert c.student.get(boxes).json()["items"] == []
    assert c.student.get(f"/api/v1/assignments/{box['id']}").status_code == 404
    assert _upload(c.student, c, box["id"]).status_code == 404

    published = c.prof.patch(
        f"/api/v1/assignments/{box['id']}", json={"status": "PUBLISHED"}, version=1
    )
    assert published.status_code == 200 and published.json()["status"] == "PUBLISHED"
    assert [b["id"] for b in c.student.get(boxes).json()["items"]] == [box["id"]]


def test_submit_resubmit_and_professor_review(api):
    c = class_with_student(api)
    box = _box(c)
    aid = box["id"]
    assert (
        c.student.get(f"/api/v1/assignments/{aid}/submissions/me").json()["code"] == "NOT_SUBMITTED"
    )

    first_files = [_upload(c.student, c, aid, name=f"part{i}.pdf").json()["id"] for i in (1, 2)]
    first = _submit(c.student, aid, first_files)
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["status"] == "SUBMITTED" and body["version"] == 1
    assert body["currentVersion"]["fileIds"] == first_files
    assert body["currentVersion"]["isLate"] is False
    assert body["currentVersion"]["receiptCode"].startswith("R-")

    # resubmit: newest counts; a stale screen gets 412
    new_file = _upload(c.student, c, aid, data=b"better answer").json()["id"]
    stale = _submit(c.student, aid, [new_file], expected=0)
    assert stale.status_code == 412
    second = _submit(c.student, aid, [new_file], expected=1)
    assert second.status_code == 201, second.text
    assert second.json()["version"] == 2 and second.json()["currentVersion"]["fileIds"] == [
        new_file
    ]
    mine = c.student.get(f"/api/v1/assignments/{aid}/submissions/me").json()
    assert mine["id"] == body["id"] and mine["version"] == 2

    # professor sees one submission (the newest version) and can download it
    listing = c.prof.get(f"/api/v1/assignments/{aid}/submissions").json()
    assert listing["totalItems"] == 1
    assert listing["items"][0]["subjectId"] == c.student.account_id
    download = c.prof.get(f"/api/v1/files/{new_file}/content")
    assert download.status_code == 200 and download.content == b"better answer"
    assert c.student.get(f"/api/v1/files/{new_file}/content").status_code == 200
    assert c.prof.get(f"/api/v1/submissions/{body['id']}").status_code == 200

    # used files cannot be submitted again
    reused = _submit(c.student, aid, [new_file], expected=2)
    assert reused.status_code == 422 and reused.json()["code"] == "FILE_NOT_USABLE"


def test_late_submission_is_flagged(api):
    c = class_with_student(api)
    box = _box(c)
    with api.app.state.database.transaction() as connection:  # move the deadline into the past
        cursor = connection.cursor()
        cursor.execute(
            """UPDATE dbo.assignments
               SET open_at = DATEADD(DAY, -2, SYSUTCDATETIME()),
                   due_at = DATEADD(DAY, -1, SYSUTCDATETIME())
               WHERE activity_id = ?""",
            box["id"],
        )
        cursor.close()
    file_id = _upload(c.student, c, box["id"]).json()["id"]
    late = _submit(c.student, box["id"], [file_id])
    assert late.status_code == 201 and late.json()["currentVersion"]["isLate"] is True


def test_who_can_submit_and_see(api):
    c = class_with_student(api)
    box = _box(c)
    aid = box["id"]
    assert _upload(c.prof, c, aid).status_code == 403  # professors don't submit
    assert _upload(c.outsider, c, aid).status_code == 404
    assert c.student.get(f"/api/v1/assignments/{aid}/submissions").status_code == 403
    assert c.outsider.get(f"/api/v1/offerings/{c.offering_id}/assignments").status_code == 404
    assert (
        c.student.post(
            f"/api/v1/offerings/{c.offering_id}/assignments",
            json={
                "title": "x",
                "topicId": 1,
                "openAt": _future(-1),
                "cutoffAt": _future(8),
                "dueAt": _future(),
                "maxScore": 1,
                "status": "DRAFT",
            },
        ).status_code
        == 403
    )

    file_id = _upload(c.student, c, aid).json()["id"]
    submission = _submit(c.student, aid, [file_id]).json()
    assert c.outsider.get(f"/api/v1/files/{file_id}/content").status_code == 404
    assert c.outsider.get(f"/api/v1/submissions/{submission['id']}").status_code == 404
    assert c.admin.get(f"/api/v1/files/{file_id}/content").status_code == 404


def test_input_rules(api, monkeypatch):
    c = class_with_student(api)
    box = _box(c)
    aid = box["id"]
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    topic_id = box["topicId"]
    in_past = c.prof.post(
        f"/api/v1/offerings/{c.offering_id}/assignments",
        json={"title": "x", "topicId": topic_id, "dueAt": past, "maxScore": 1, "status": "DRAFT"},
    )
    assert in_past.status_code == 400

    six = [_upload(c.student, c, aid, name=f"{i}.pdf").json()["id"] for i in range(6)]
    assert _submit(c.student, aid, six).status_code in (400, 422)
    other_box = _box(c, title="Homework 2")
    foreign = _upload(c.student, c, other_box["id"]).json()["id"]
    wrong_box = _submit(c.student, aid, [foreign])
    assert wrong_box.status_code == 422 and wrong_box.json()["code"] == "FILE_NOT_USABLE"

    monkeypatch.setattr(submission_service, "MAX_SUBMISSION_BYTES", 5)
    too_big = _upload(c.student, c, aid, data=b"123456")
    assert too_big.status_code == 413 and too_big.json()["code"] == "FILE_TOO_LARGE"


def test_due_date_keeps_the_same_instant(api):
    c = class_with_student(api)
    box = _box(c, dueAt="2030-01-01T07:00:00+07:00")  # 07:00 in Vietnam = 00:00 UTC
    assert box["dueAt"] in ("2030-01-01T00:00:00Z", "2030-01-01T00:00:00+00:00")
