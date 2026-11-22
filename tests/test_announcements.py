"""Announcements and the personal inbox (notifications)."""

from datetime import UTC, datetime, timedelta

from tests.helpers import class_with_student
from tests.test_grading import _enroll_outsider, _grade, _release, _submitted
from tests.test_submissions import _box


def _inbox(user, **params):
    response = user.get("/api/v1/me/notifications", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _events(user):
    return [n["eventType"] for n in _inbox(user)["items"]]


def test_professor_posts_and_class_is_notified(api):
    c = class_with_student(api)
    url = f"/api/v1/offerings/{c.offering_id}/announcements"
    for title in ("Welcome", "Room change"):
        posted = c.prof.post(url, json={"title": title, "body": "See you on Monday."})
        assert posted.status_code == 201, posted.text
    assert posted.json()["author"]["displayName"] == "Prof"

    listed = c.student.get(url).json()
    assert [a["title"] for a in listed["items"]] == ["Room change", "Welcome"]  # newest first

    inbox = _inbox(c.student)
    assert inbox["unreadCount"] == 2
    newest = inbox["items"][0]
    assert newest["eventType"] == "ANNOUNCEMENT" and newest["targetType"] == "ANNOUNCEMENT"
    assert newest["message"] == "A course announcement was posted."
    assert newest["targetId"] == posted.json()["id"] and newest["read"] is False
    assert _inbox(c.prof)["items"] == []  # the author is not notified

    assert c.student.post(url, json={"title": "x", "body": "y"}).status_code == 403
    assert c.outsider.get(url).status_code == 404
    assert c.prof.post(url, json={"title": "  ", "body": "y"}).status_code == 400


def test_assignment_published_and_due_date_changed(api):
    c = class_with_student(api)
    _box(c, title="Essay")  # published at once
    draft = _box(c, status="DRAFT", title="Lab")
    assert _events(c.student) == ["ASSIGNMENT_PUBLISHED"]

    published = c.prof.patch(
        f"/api/v1/assignments/{draft['id']}", json={"status": "PUBLISHED"}, version=1
    )
    assert published.status_code == 200
    assert _events(c.student) == ["ASSIGNMENT_PUBLISHED", "ASSIGNMENT_PUBLISHED"]

    later = (datetime.now(UTC) + timedelta(days=7, hours=12)).isoformat()
    moved = c.prof.patch(f"/api/v1/assignments/{draft['id']}", json={"dueAt": later}, version=2)
    assert moved.status_code == 200, moved.text
    first = _inbox(c.student)["items"][0]
    assert first["eventType"] == "DUE_DATE_CHANGED"
    assert first["message"] == "An assignment deadline changed."


def test_grades_released_reach_only_graded_students(api):
    c = class_with_student(api)
    _enroll_outsider(c)
    box, submission_id = _submitted(c)
    _grade(c.prof, submission_id, score=9)
    _release(c.prof, box["id"])
    assert _events(c.student)[0] == "GRADES_RELEASED"
    assert "GRADES_RELEASED" not in _events(c.outsider)  # out@ has no grade

    _release(c.prof, box["id"])  # nothing new: nobody is notified again
    assert _events(c.student).count("GRADES_RELEASED") == 1


def test_mark_read(api):
    c = class_with_student(api)
    c.prof.post(
        f"/api/v1/offerings/{c.offering_id}/announcements", json={"title": "Hi", "body": "Hello"}
    )
    note = _inbox(c.student)["items"][0]
    url = f"/api/v1/me/notifications/{note['id']}/read"
    assert c.outsider.put(url).status_code == 404  # not their notification
    assert c.student.put(url).status_code == 204
    inbox = _inbox(c.student)
    assert inbox["unreadCount"] == 0 and inbox["items"][0]["read"] is True
    assert _inbox(c.student, unreadOnly=True)["items"] == []
