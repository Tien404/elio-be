"""Personal inbox (class diagram: NotificationService).

Other services call notify_course() inside their own transaction when something happens
(announcement posted, assignment published, due date changed, grades released). The
person who caused the event is never notified (FR-13).
"""

from typing import Any

from app.api.schemas.common import utc_payload
from app.core.errors import FeatureNotImplemented, not_found
from app.domain.context import Actor
from app.infrastructure.db.repositories.notification_repository import NotificationRepository
from app.infrastructure.db.sql import Sql

MESSAGES = {
    "ANNOUNCEMENT": "A course announcement was posted.",
    "ASSIGNMENT_PUBLISHED": "An assignment was published.",
    "DUE_DATE_CHANGED": "An assignment deadline changed.",
    "GRADES_RELEASED": "An assignment grade was published or updated.",
    "QUIZ_PUBLISHED": "A quiz was published.",
    "QUIZ_RESULT_RELEASED": "A quiz result is available.",
    "INSTRUCTOR_ADDED": "An instructor joined the teaching team.",
    "LEAD_TRANSFERRED": "The lead instructor changed.",
}


def notify_course(
    sql: Sql,
    *,
    offering_id: int,
    actor_id: int,
    event_type: str,
    title: str,
    target_type: str,
    target_id: int,
    event_key: str,
    recipients: list[int] | None = None,
    students_only: bool = True,
) -> None:
    """Put one notification in each recipient's inbox (default: the class's students).
    event_key makes repeats harmless: the same key never reaches a person twice."""
    repo = NotificationRepository(sql)
    if recipients is None:
        recipients = repo.class_members(offering_id, students_only=students_only)
    message = MESSAGES[event_type].format(code=repo.course_code(offering_id), title=title)
    if len(message) > 500:
        message = message[:497] + "..."
    for recipient_id in recipients:
        if recipient_id == actor_id:
            continue  # never notify the person who did it
        repo.insert_notification(
            recipient_id=recipient_id,
            actor_id=actor_id,
            offering_id=offering_id,
            event_type=event_type,
            message=message,
            target_type=target_type,
            target_id=target_id,
            event_key=event_key,
        )


class NotificationService:
    def __init__(self, database=None):
        self.database = database

    def list_personal(
        self,
        *,
        actor: Actor,
        page: int,
        page_size: int,
        unread_only: bool = False,
        offering_id=None,
        state="ALL",
        event=None,
        search=None,
    ) -> dict[str, Any]:
        """My inbox, newest first, with the number of unread notifications."""
        with self.database.transaction() as connection:
            rows, total, unread = NotificationRepository(Sql(connection)).inbox(
                actor.user_id,
                unread_only=unread_only,
                offset=0,
                limit=2147483647,
            )
        all_items = [notification_view(r) for r in rows]
        filtered = [
            item
            for item in all_items
            if (offering_id is None or item["offeringId"] == offering_id)
            and (state == "ALL" or item["status"] == state)
            and (not event or item["event"] == event)
            and (not search or search.lower() in item["preview"].lower())
        ]
        total = len(filtered)
        items = filtered[(page - 1) * page_size : page * page_size]
        return {
            "unread": unread,
            "rows": {
                "items": items,
                "page": page,
                "pageSize": page_size,
                "totalItems": total,
                "totalPages": (total + page_size - 1) // page_size,
            },
            "items": items,
            "unreadCount": unread,
            "page": page,
            "pageSize": page_size,
            "totalItems": total,
            "totalPages": (total + page_size - 1) // page_size,
        }

    def mark_notification_read(self, *, actor: Actor, notification_id: int) -> None:
        with self.database.transaction() as connection:
            if not NotificationRepository(Sql(connection)).mark_read(
                notification_id, actor.user_id
            ):
                raise not_found("Notification")

    # ------------------------------------------- contract operations not used
    def retry_pending(self, **kwargs: object):
        raise FeatureNotImplemented("NotificationService.retry_pending")

    def get_notifications(self, **kwargs: object):
        raise FeatureNotImplemented("NotificationService.get_notifications")


def notification_view(row: dict[str, Any]) -> dict[str, Any]:
    event = {
        "ANNOUNCEMENT": "ANNOUNCEMENT_PUBLISHED",
        "DUE_DATE_CHANGED": "ASSIGNMENT_DEADLINE_CHANGED",
        "GRADES_RELEASED": "ASSIGNMENT_GRADE_PUBLISHED",
    }.get(row["event_type"], row["event_type"])
    href = (
        f"/offerings/{row['offering_id']}/announcements"
        if row["target_type"] == "ANNOUNCEMENT"
        else f"/results?offeringId={row['offering_id']}"
        if row["target_type"] in {"GRADE", "SUBMISSION"} or row["event_type"] == "GRADES_RELEASED"
        else f"/{ {'QUIZ': 'quizzes', 'QUIZ_ATTEMPT': 'quiz-attempts', 'ASSIGNMENT': 'assignments'}.get(row['target_type'], 'offerings') }/{row['target_id']}"
    )
    return {
        "event": event,
        "targetKind": row["target_type"],
        "preview": MESSAGES.get(row["event_type"], "A course update is available."),
        "status": "READ" if row["is_read"] else "UNREAD",
        "href": href,
        "id": row["notification_id"],
        "eventType": row["event_type"],
        "message": MESSAGES.get(row["event_type"], "A course update is available."),
        "offeringId": row["offering_id"],
        "targetType": row["target_type"],
        "targetId": row["target_id"],
        "actor": {"id": row["actor_id"], "displayName": row["actor_name"]}
        if row["actor_id"]
        else None,
        "read": bool(row["is_read"]),
        "createdAt": utc_payload(row["created_at"]),
    }
