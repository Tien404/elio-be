"MySQL SQL for announcements and the personal inbox (notifications). Never commits."

from typing import Any

from app.infrastructure.db.sql import Sql


class NotificationRepository:
    def __init__(self, sql: Sql):
        self.sql = sql

    # ------------------------------------------------------------ announcements
    def insert_announcement(
        self, *, offering_id: int, author_id: int, title: str, body: str
    ) -> int:
        return self.sql.insert(
            """INSERT INTO announcements (offering_id, author_id, title, body, status, published_at)
               VALUES (%s, %s, %s, %s, 'PUBLISHED', UTC_TIMESTAMP(6))""",
            offering_id,
            author_id,
            title,
            body,
        )

    def list_announcements(
        self, offering_id: int, *, offset: int, limit: int
    ) -> tuple[list[dict[str, Any]], int]:
        where = "a.offering_id = %s AND a.status = 'PUBLISHED'"
        total = self.sql.scalar(
            f"SELECT COUNT(*) FROM announcements AS a WHERE {where}", offering_id
        )
        rows = self.sql.all(
            f"""SELECT a.announcement_id, a.offering_id, a.title, a.body, a.published_at,
                       a.author_id, u.full_name AS author_name
                FROM announcements AS a JOIN users AS u ON u.user_id = a.author_id
                WHERE {where}
                ORDER BY a.published_at DESC, a.announcement_id DESC LIMIT %s, %s""",
            offering_id,
            offset,
            limit,
        )
        return rows, total

    def get_announcement(self, announcement_id: int) -> dict[str, Any] | None:
        return self.sql.one(
            """SELECT a.announcement_id, a.offering_id, a.title, a.body, a.published_at,
                      a.author_id, u.full_name AS author_name
               FROM announcements AS a JOIN users AS u ON u.user_id = a.author_id
               WHERE a.announcement_id = %s AND a.status='PUBLISHED'""",
            announcement_id,
        )

    # -------------------------------------------------------------- recipients
    def class_members(self, offering_id: int, *, students_only: bool) -> list[int]:
        where = "offering_id = %s AND status = 'ACTIVE'"
        if students_only:
            where += " AND course_role = 'STUDENT'"
        return [
            r["user_id"]
            for r in self.sql.all(
                f"SELECT user_id FROM course_memberships WHERE {where}", offering_id
            )
        ]

    def course_code(self, offering_id: int) -> str:
        return self.sql.scalar(
            """SELECT c.course_code FROM course_offerings AS o
               JOIN courses AS c ON c.course_id = o.course_id WHERE o.offering_id = %s""",
            offering_id,
        )

    # ------------------------------------------------------------------- inbox
    def insert_notification(
        self,
        *,
        recipient_id: int,
        actor_id: int | None,
        offering_id: int | None,
        event_type: str,
        message: str,
        target_type: str,
        target_id: int,
        event_key: str,
    ) -> None:
        """INSERT IGNORE: the same event never reaches the same person twice."""
        self.sql.execute(
            """INSERT IGNORE INTO notifications (recipient_id, actor_id, offering_id, event_type,
                   message, target_type, target_id, event_key)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            recipient_id,
            actor_id,
            offering_id,
            event_type,
            message,
            target_type,
            target_id,
            event_key,
        )

    def inbox(
        self, recipient_id: int, *, unread_only: bool, offset: int, limit: int
    ) -> tuple[list[dict[str, Any]], int, int]:
        visible = """n.recipient_id=%s AND EXISTS (
            SELECT 1 FROM course_memberships m JOIN course_offerings o ON o.offering_id=m.offering_id
            WHERE m.offering_id=n.offering_id AND m.user_id=n.recipient_id AND m.status='ACTIVE'
            AND (o.state<>'DRAFT' OR m.course_role<>'STUDENT')) AND (
            (n.target_type IN ('ASSIGNMENT','QUIZ') AND EXISTS (
                SELECT 1 FROM activities a WHERE a.activity_id=n.target_id AND a.offering_id=n.offering_id AND a.status='PUBLISHED'))
            OR (n.target_type='ANNOUNCEMENT' AND EXISTS (
                SELECT 1 FROM announcements a WHERE a.announcement_id=n.target_id AND a.offering_id=n.offering_id AND a.status='PUBLISHED'))
            OR (n.target_type='QUIZ_ATTEMPT' AND EXISTS (
                SELECT 1 FROM quiz_attempts t JOIN activities a ON a.activity_id=t.quiz_id
                WHERE t.attempt_id=n.target_id AND a.offering_id=n.offering_id AND a.status='PUBLISHED'
                AND t.student_id=n.recipient_id AND t.released_at IS NOT NULL))
            OR (n.target_type='OFFERING' AND n.target_id=n.offering_id))"""
        where = visible + (" AND n.is_read=0" if unread_only else "")
        total = self.sql.scalar(
            f"SELECT COUNT(*) FROM notifications AS n WHERE {where}", recipient_id
        )
        unread = self.sql.scalar(
            f"SELECT COUNT(*) FROM notifications n WHERE {visible} AND n.is_read=0", recipient_id
        )
        rows = self.sql.all(
            f"""SELECT n.notification_id, n.offering_id, n.event_type, n.message, n.target_type,
                       n.target_id, n.created_at, n.is_read, n.actor_id, u.full_name AS actor_name
                FROM notifications AS n LEFT JOIN users AS u ON u.user_id = n.actor_id
                WHERE {where}
                ORDER BY n.created_at DESC, n.notification_id DESC LIMIT %s, %s""",
            recipient_id,
            offset,
            limit,
        )
        return rows, total, unread

    def mark_read(self, notification_id: int, recipient_id: int) -> bool:
        """False when the notification is not this person's."""
        found = self.sql.scalar(
            "SELECT COUNT(*) FROM notifications WHERE notification_id = %s AND recipient_id = %s AND EXISTS (SELECT 1 FROM course_memberships m WHERE m.offering_id=notifications.offering_id AND m.user_id=notifications.recipient_id AND m.status='ACTIVE')",
            notification_id,
            recipient_id,
        )
        if found:
            self.sql.execute(
                "UPDATE notifications SET is_read = 1 WHERE notification_id = %s", notification_id
            )
        return bool(found)
