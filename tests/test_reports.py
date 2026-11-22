"""Read-only overviews: admin class list, audit log, gradebook + CSV, progress, calendar."""

from datetime import UTC, datetime, timedelta

from tests.helpers import class_with_student
from tests.test_grading import _enroll_outsider, _grade, _submitted
from tests.test_quizzes import _published, _true_false


def _text_material(c, status="PUBLISHED"):
    topic = c.prof.post(f"/api/v1/offerings/{c.offering_id}/topics", json={"title": "Notes"})
    response = c.prof.post(
        f"/api/v1/offerings/{c.offering_id}/resources",
        json={
            "title": "Read me",
            "topicId": topic.json()["id"],
            "kind": "TEXT",
            "body": "Welcome to the class",
            "mandatory": True,
            "status": status,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _take_quiz(c, quiz, option=1):
    attempt = c.student.post(f"/api/v1/quizzes/{quiz['id']}/attempts").json()
    question = attempt["questions"][0]["id"]
    c.student.put(
        f"/api/v1/quiz-attempts/{attempt['id']}/answers/{question}",
        json={"option": option},
        version=c.student.get(
            (f"/api/v1/quiz-attempts/{attempt['id']}/answers/{question}")
            .split("/answers")[0]
            .removesuffix("/seal")
        )
        .json()
        .get("version", 1),
    )
    return c.student.post(
        f"/api/v1/quiz-attempts/{attempt['id']}/seal",
        version=c.student.get(
            (f"/api/v1/quiz-attempts/{attempt['id']}/seal")
            .split("/answers")[0]
            .removesuffix("/seal")
        )
        .json()
        .get("version", 1),
    ).json()


# ------------------------------------------------------------------- admin
def test_admin_lists_every_class(api):
    c = class_with_student(api)
    page = c.admin.get("/api/v1/admin/offerings")
    assert page.status_code == 200, page.text
    (row,) = page.json()["items"]
    assert row["courseCode"] == "CS1001" and row["status"] == "OPEN"
    assert row["lead"]["displayName"] == "Prof" and row["studentCount"] == 1

    assert c.admin.get("/api/v1/admin/offerings?q=cs10").json()["totalItems"] == 1
    assert c.admin.get("/api/v1/admin/offerings?q=nothing").json()["totalItems"] == 0
    assert c.admin.get("/api/v1/admin/offerings?status=DRAFT").json()["totalItems"] == 0
    assert c.prof.get("/api/v1/admin/offerings").status_code == 403


def test_admin_reads_the_audit_log(api):
    c = class_with_student(api)
    box, submission_id = _submitted(c)
    _grade(c.prof, submission_id, score=7)
    log = c.admin.get("/api/v1/admin/audit-entries").json()
    assert log["totalItems"] > 3
    newest = log["items"][0]
    assert newest["action"] == "GRADE_SAVED" and newest["actor"]["displayName"] == "Prof"
    assert "7" not in str(newest["details"])  # scores never go into the audit log

    only = c.admin.get("/api/v1/admin/audit-entries?action=SUBMISSION_CONFIRMED").json()
    assert [e["targetId"] for e in only["items"]] == [submission_id]
    mine = c.admin.get(f"/api/v1/admin/audit-entries?actorId={c.student.account_id}").json()
    assert all(e["actor"]["id"] == c.student.account_id for e in mine["items"])
    assert c.student.get("/api/v1/admin/audit-entries").status_code == 403


# --------------------------------------------------------------- gradebook
def test_gradebook_and_csv(api):
    import csv
    import io

    c = class_with_student(api)
    _enroll_outsider(c)
    box, sid = _submitted(c, title="Essay", weight=40)
    quiz = _published(c, _true_false(), title="Quiz 1", weight=60)
    _take_quiz(c, quiz)
    assert _grade(c.prof, sid, score=8.5).status_code == 200
    missing = c.prof.post(
        f"/api/v1/assignments/{box['id']}/missing-work-decisions",
        json={
            "studentId": c.outsider.account_id,
            "specialMark": "ABSENT",
            "zeroReason": "No submission",
        },
    )
    assert missing.status_code == 200, missing.text
    assert c.prof.put(f"/api/v1/assignments/{box['id']}/grade-release").status_code == 200
    response = c.prof.get(f"/api/v1/offerings/{c.offering_id}/gradebook")
    assert response.status_code == 200, response.text
    book = response.json()
    students = {r["student"]["displayName"]: r for r in book["rows"]}
    assert students["Stu"]["total"]["grade"] == 9.4
    assert students["Stu"]["total"]["final"] is True
    assert students["Out"]["total"]["final"] is False
    assert (
        next(i for i in students["Out"]["items"] if i["activityId"] == box["id"])["specialCode"]
        == 11
    )
    exported = c.prof.get(f"/api/v1/offerings/{c.offering_id}/gradebook.csv")
    rows = list(csv.reader(io.StringIO(exported.content.decode("utf-8-sig"))))
    assert rows[0][-2:] == ["Total (/10)", "Percentage"]
    assert any(r[1] == "Stu" and r[-2:] == ["9.4", "94.0"] for r in rows[1:])
    assert any(r[1] == "Out" and "11" in r and "" in r for r in rows[1:])
    assert c.student.get(f"/api/v1/offerings/{c.offering_id}/gradebook").status_code == 403
    assert c.admin.get(f"/api/v1/offerings/{c.offering_id}/gradebook.csv").status_code == 404


def test_progress_counts_what_students_did(api):
    c = class_with_student(api)
    _enroll_outsider(c)
    material = _text_material(c)
    _text_material(c, status="DRAFT")
    _submitted(c, mandatory=True)
    quiz = _published(c, _true_false(), mandatory=True)
    c.student.put(f"/api/v1/resources/{material}/completion")
    _take_quiz(c, quiz)
    response = c.prof.get(f"/api/v1/offerings/{c.offering_id}/progress")
    assert response.status_code == 200, response.text
    rows = {r["displayName"]: r for r in response.json()["rows"]["items"]}
    assert (
        rows["Stu"]["completed"] == 3
        and rows["Stu"]["total"] == 3
        and rows["Stu"]["percent"] == 100
    )
    assert rows["Out"]["completed"] == 0
    own = c.student.get("/api/v1/me/progress").json()["rows"]["items"]
    assert len(own) == 1 and own[0]["percent"] == 100
    assert (
        len(c.student.get(f"/api/v1/offerings/{c.offering_id}/progress").json()["rows"]["items"])
        == 1
    )


def test_calendar_shows_upcoming_work(api):
    c = class_with_student(api)
    _submitted(c, title="Essay")
    _published(c, _true_false(), title="Quiz 1")
    response = c.student.get("/api/v1/me/calendar")
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert {i["kind"] for i in items} == {"QUIZ_CLOSE", "ASSIGNMENT_DUE"}
    assert all(i["at"].endswith("Z") or i["at"].endswith("+00:00") for i in items)
    wider = c.student.get(
        "/api/v1/me/calendar",
        params={
            "from": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
            "to": (datetime.now(UTC) + timedelta(days=90)).isoformat(),
        },
    )
    assert {i["kind"] for i in wider.json()["items"]} == {
        "QUIZ_OPEN",
        "QUIZ_CLOSE",
        "ASSIGNMENT_DUE",
    }
    assert c.outsider.get("/api/v1/me/calendar").json()["items"] == []
    assert (
        c.student.get(
            "/api/v1/me/calendar",
            params={
                "from": datetime.now(UTC).isoformat(),
                "to": (datetime.now(UTC) + timedelta(days=400)).isoformat(),
            },
        ).status_code
        == 400
    )
