"""Grade records (one grade, its history, single release) and receipt lookup."""

from tests.helpers import class_with_student
from tests.test_grading import _enroll_outsider, _grade, _page, _submitted
from tests.test_submissions import _box, _upload


def _records(c, box):
    response = c.prof.get(f"/api/v1/assignments/{box['id']}/grade-records")
    assert response.status_code == 200, response.text
    return {r["student"]["displayName"]: r["grade"] for r in response.json()["items"]}


def test_grade_list_record_and_history(api):
    c = class_with_student(api)
    _enroll_outsider(c)
    box, submission_id = _submitted(c)
    _grade(c.prof, submission_id, score=7)
    _grade(c.prof, submission_id, score=8, feedback="Better")

    rows = _records(c, box)
    assert rows["Stu"]["grade"] == 8 and rows["Stu"]["status"] == "DRAFT"
    assert rows["Out"]["status"] == "NOT_GRADED" and rows["Out"]["gradeId"] is None
    assert c.student.get(f"/api/v1/assignments/{box['id']}/grade-records").status_code == 403

    url = f"/api/v1/grade-records/{rows['Stu']['gradeId']}"
    record = c.prof.get(url).json()
    assert record["status"] == "DRAFT" and record["current"]["grade"] == 8
    assert record["released"] is None and record["studentIds"] == [c.student.account_id]
    assert [r["revisionNo"] for r in record["revisions"]] == [2, 1]
    assert record["revisions"][1]["grade"] == 7
    assert record["revisions"][0]["revisedBy"]["displayName"] == "Prof"
    assert c.student.get(url).status_code == 404  # nothing released yet

    revised = c.prof.post(
        f"{url}/revisions",
        json={"score": 9, "expectedSubmissionVersion": 1, "sourceVersionNo": 1},
        version=record["version"],
    )
    assert revised.status_code == 201, revised.text
    assert revised.json()["current"]["grade"] == 9 and len(revised.json()["revisions"]) == 3
    too_high = c.prof.post(
        f"{url}/revisions",
        json={"score": 11, "expectedSubmissionVersion": 1, "sourceVersionNo": 1},
        version=revised.json()["version"],
    )
    assert too_high.status_code == 422


def test_release_one_grade(api):
    c = class_with_student(api)
    _enroll_outsider(c)
    box = _box(c)
    submissions = []
    for user, score in ((c.student, 6), (c.outsider, 9)):
        file_id = _upload(user, c, box["id"]).json()["id"]
        submission = user.post(
            f"/api/v1/assignments/{box['id']}/submissions",
            json={"expectedVersion": 0, "fileIds": [file_id]},
        ).json()
        submissions.append((submission["id"], score))
    for sid, score in submissions:
        _grade(c.prof, sid, score=score)

    stu_grade = _records(c, box)["Stu"]["gradeId"]
    released = c.prof.put(
        f"/api/v1/grade-records/{stu_grade}/publication",
        json={
            "revisionNo": c.prof.get(f"/api/v1/grade-records/{stu_grade}").json()["draftRevision"][
                "revisionNo"
            ]
        },
        version=c.prof.get(f"/api/v1/grade-records/{stu_grade}").json()["version"],
    )
    assert released.status_code == 200, released.text
    assert released.json()["status"] == "RELEASED" and released.json()["released"]["grade"] == 6

    assert _page(c.student, c).json()["items"][0]["grade"] == 6
    assert _page(c.outsider, c, c.outsider.account_id).json()["items"][0]["grade"] is None
    events = [n["eventType"] for n in c.student.get("/api/v1/me/notifications").json()["items"]]
    assert events.count("GRADES_RELEASED") == 1
    assert "GRADES_RELEASED" not in [
        n["eventType"] for n in c.outsider.get("/api/v1/me/notifications").json()["items"]
    ]

    own = c.student.get(f"/api/v1/grade-records/{stu_grade}").json()
    assert own["current"]["grade"] == 6 and own["revisions"] is None  # no history for students
    assert c.outsider.get(f"/api/v1/grade-records/{stu_grade}").status_code == 404
    assert (
        c.student.put(
            f"/api/v1/grade-records/{stu_grade}/publication", json={"revisionNo": 1}, version=1
        ).status_code
        == 403
    )

    c.prof.put(
        f"/api/v1/grade-records/{stu_grade}/publication",
        json={
            "revisionNo": c.prof.get(f"/api/v1/grade-records/{stu_grade}").json()["draftRevision"][
                "revisionNo"
            ]
        },
        version=c.prof.get(f"/api/v1/grade-records/{stu_grade}").json()["version"],
    )  # again: nothing new
    events = [n["eventType"] for n in c.student.get("/api/v1/me/notifications").json()["items"]]
    assert events.count("GRADES_RELEASED") == 1


def test_receipt_lookup_and_repeat_safe_hand_in(api):
    from tests.test_main_adaptation import test_original_receipt_replay_and_changed_payload

    test_original_receipt_replay_and_changed_payload(api)
