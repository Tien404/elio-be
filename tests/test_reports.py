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
            "status": status,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _take_quiz(c, quiz, option=1):
    attempt = c.student.post(f"/api/v1/quizzes/{quiz['id']}/attempts").json()
    question = attempt["questions"][0]["id"]
    c.student.put(
        f"/api/v1/quiz-attempts/{attempt['id']}/answers/{question}", json={"option": option}
    )
    return c.student.post(f"/api/v1/quiz-attempts/{attempt['id']}/seal").json()


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
    c = class_with_student(api)
    _enroll_outsider(c)
    box, submission_id = _submitted(c, title="Essay")
    quiz = _published(c, _true_false(), title="Quiz 1")
    _grade(c.prof, submission_id, score=8.5)
    c.prof.post(
        f"/api/v1/assignments/{box['id']}/missing-work-decisions",
        json={"studentId": c.outsider.account_id, "specialMark": "ABSENT"},
    )
    _take_quiz(c, quiz)  # stu@ answers True: full marks

    book = c.prof.get(f"/api/v1/offerings/{c.offering_id}/gradebook")
    assert book.status_code == 200, book.text
    book = book.json()
    assert [col["title"] for col in book["columns"]] == ["Quiz 1", "Essay"]  # by date
    assert book["total"]["rangeMax"] == 20
    by_name = {r["student"]["displayName"]: r for r in book["rows"]}
    assert [i["grade"] for i in by_name["Stu"]["items"]] == [10, 8.5]
    assert by_name["Stu"]["total"]["grade"] == 18.5
    assert by_name["Out"]["items"][1]["specialCode"] == 11
    assert by_name["Out"]["total"]["grade"] is None  # quiz not taken yet

    csv = c.prof.get(f"/api/v1/offerings/{c.offering_id}/gradebook.csv")
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    assert 'filename="CS1001-01-2026-1-grades.csv"' in csv.headers["content-disposition"]
    lines = csv.content.decode("utf-8-sig").splitlines()
    assert lines[0] == "Student code,Name,Quiz 1 (/10),Essay (/10),Total (/20),Percentage"
    assert any(line.endswith(",Stu,10.0,8.5,18.5,92.5") for line in lines[1:])
    assert any(",Out,,11," in line for line in lines[1:])

    assert c.student.get(f"/api/v1/offerings/{c.offering_id}/gradebook").status_code == 403
    assert c.admin.get(f"/api/v1/offerings/{c.offering_id}/gradebook.csv").status_code == 404


# ---------------------------------------------------------------- progress
def test_progress_counts_what_students_did(api):
    c = class_with_student(api)
    _enroll_outsider(c)
    material = _text_material(c)
    _text_material(c, status="DRAFT")  # drafts do not count
    _submitted(c)
    quiz = _published(c, _true_false())
    c.student.put(f"/api/v1/resources/{material}/completion")
    _take_quiz(c, quiz)

    progress = c.prof.get(f"/api/v1/offerings/{c.offering_id}/progress")
    assert progress.status_code == 200, progress.text
    rows = {r["student"]["displayName"]: r for r in progress.json()["students"]}
    stu = rows["Stu"]
    assert stu["materials"] == {"done": 1, "total": 1}
    assert stu["assignments"] == {"done": 1, "total": 1}
    assert stu["quizzes"] == {"done": 1, "total": 1} and stu["percent"] == 100
    assert rows["Out"]["percent"] == 0

    mine = c.student.get("/api/v1/me/progress").json()["items"]
    assert len(mine) == 1 and mine[0]["courseCode"] == "CS1001" and mine[0]["percent"] == 100
    assert c.student.get(f"/api/v1/offerings/{c.offering_id}/progress").status_code == 403
    assert c.prof.get("/api/v1/me/progress").status_code == 403


# ---------------------------------------------------------------- calendar
def test_calendar_shows_upcoming_work(api):
    c = class_with_student(api)
    box, _ = _submitted(c, title="Essay")  # due in 7 days, submitted
    _submitted_later = c.prof.post(
        f"/api/v1/offerings/{c.offering_id}/assignments",
        json={
            "title": "Far away",
            "openAt": datetime.now(UTC).isoformat(),
            "dueAt": (datetime.now(UTC) + timedelta(days=60)).isoformat(),
            "cutoffAt": (datetime.now(UTC) + timedelta(days=60)).isoformat(),
            "maxScore": 10,
            "status": "PUBLISHED",
        },
    )
    assert _submitted_later.status_code == 201
    quiz = _published(c, _true_false(), title="Quiz 1")  # closes in 2 hours

    calendar = c.student.get("/api/v1/me/calendar")
    assert calendar.status_code == 200, calendar.text
    items = calendar.json()["items"]
    assert [(i["title"], i["type"], i["done"]) for i in items] == [
        ("Quiz 1", "QUIZ", False),
        ("Essay", "ASSIGNMENT", True),
    ]
    assert items[0]["opensAt"] is not None and items[1]["opensAt"] is None

    later = c.student.get(
        "/api/v1/me/calendar",
        params={
            "from": datetime.now(UTC).isoformat(),
            "to": (datetime.now(UTC) + timedelta(days=90)).isoformat(),
        },
    ).json()["items"]
    assert "Far away" in [i["title"] for i in later]
    teacher = c.prof.get("/api/v1/me/calendar").json()["items"]
    assert {i["activityId"] for i in teacher} == {box["id"], quiz["id"]}
    assert all(i["done"] is None for i in teacher)
    assert c.outsider.get("/api/v1/me/calendar").json()["items"] == []
    too_long = c.student.get(
        "/api/v1/me/calendar",
        params={
            "from": datetime.now(UTC).isoformat(),
            "to": (datetime.now(UTC) + timedelta(days=400)).isoformat(),
        },
    )
    assert too_long.status_code == 400
