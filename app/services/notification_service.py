"""Personal inbox (class diagram: NotificationService).

Other services call notify_course() inside their own transaction when something happens
(announcement posted, assignment published, due date changed, grades released). The
person who caused the event is never notified (FR-13).
"""

from typing import Any

from app.core.errors import FeatureNotImplemented, not_found
from app.domain.context import Actor
from app.infrastructure.db.repositories.notification_repository import NotificationRepository
from app.infrastructure.db.sql import Sql

MESSAGES = {
    "ANNOUNCEMENT": "New announcement in {code}: {title}",
    "ASSIGNMENT_PUBLISHED": "New assignment in {code}: {title}",
    "DUE_DATE_CHANGED": "Due date changed in {code}: {title}",
    "GRADES_RELEASED": "Grades released in {code}: {title}",
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
        self, *, actor: Actor, page: int, page_size: int, unread_only: bool = False
    ) -> dict[str, Any]:
        """My inbox, newest first, with the number of unread notifications."""
        with self.database.transaction() as connection:
            rows, total, unread = NotificationRepository(Sql(connection)).inbox(
                actor.user_id,
                unread_only=unread_only,
                offset=(page - 1) * page_size,
                limit=page_size,
            )
        return {
            "items": [notification_view(r) for r in rows],
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
    return {
        "id": row["notification_id"],
        "eventType": row["event_type"],
        "message": row["message"],
        "offeringId": row["offering_id"],
        "targetType": row["target_type"],
        "targetId": row["target_id"],
        "actor": {"id": row["actor_id"], "displayName": row["actor_name"]}
        if row["actor_id"]
        else None,
        "read": bool(row["is_read"]),
        "createdAt": row["created_at"],
    }
