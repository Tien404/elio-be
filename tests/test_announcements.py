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


def test_legacy_notification_events_keep_inbox_contract_and_read_state(api, database):
    from app.infrastructure.db.repositories.notification_repository import NotificationRepository
    from app.infrastructure.db.sql import Sql
    from app.services.notification_service import MESSAGES

    c = class_with_student(api)
    box = _box(c)
    announcement = c.prof.post(
        f"/api/v1/offerings/{c.offering_id}/announcements",
        json={"title": "Current announcement", "body": "Class update"},
    ).json()
    legacy = {
        "ANNOUNCEMENT_PUBLISHED": ("ANNOUNCEMENT", "ANNOUNCEMENT", announcement["id"]),
        "ASSIGNMENT_DEADLINE_CHANGED": ("DUE_DATE_CHANGED", "ASSIGNMENT", box["id"]),
        "ASSIGNMENT_GRADE_PUBLISHED": ("GRADES_RELEASED", "ASSIGNMENT", box["id"]),
        "ASSIGNMENT_GRADE_UPDATED": ("GRADES_RELEASED", "ASSIGNMENT", box["id"]),
    }
    with database.transaction() as connection:
        repo = NotificationRepository(Sql(connection))
        for event, (_, target_type, target_id) in legacy.items():
            repo.insert_notification(
                recipient_id=c.student.account_id,
                actor_id=c.prof.account_id,
                offering_id=c.offering_id,
                event_type=event,
                message="Historical notification",
                target_type=target_type,
                target_id=target_id,
                event_key=f"legacy:{event}",
            )
    inbox = _inbox(c.student)
    assert inbox["items"] == inbox["rows"]["items"]
    assert inbox["unreadCount"] == inbox["unread"] == inbox["totalItems"] == 6
    for event, (canonical, _, _) in legacy.items():
        item = next(item for item in inbox["items"] if item["event"] == event)
        assert item["eventType"] == canonical
        assert item["preview"] == item["message"] == MESSAGES[canonical]
        if canonical == "GRADES_RELEASED":
            assert item["href"] == f"/results?offeringId={c.offering_id}"
    page = _inbox(c.student, pageSize=2)
    assert len(page["items"]) == 2 and page["totalPages"] == 3
    updated = _inbox(c.student, kind="ASSIGNMENT_GRADE_UPDATED")["items"]
    assert len(updated) == 1
    url = f"/api/v1/me/notifications/{updated[0]['id']}/read"
    assert c.outsider.put(url).status_code == 404
    assert c.student.put(url).status_code == 204
    assert _inbox(c.student)["unread"] == 5
    assert _inbox(c.student, state="READ")["items"][0]["id"] == updated[0]["id"]
    with database.read_connection() as connection:
        stored = Sql(connection).all(
            "SELECT event_type FROM notifications WHERE event_key LIKE 'legacy:%%'"
        )
    assert {row["event_type"] for row in stored} == set(legacy)
