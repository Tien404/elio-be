"MySQL SQL for read-only overviews: admin class list, audit log, progress, calendar. Never commits."

from datetime import datetime
from typing import Any

from app.infrastructure.db.sql import Sql, like_literal

# Per student of a class: what is published and how much of it the student has done.
_PROGRESS_SELECT = """SELECT u.user_id, u.full_name, st.student_code,
        (SELECT COUNT(*) FROM materials AS mt JOIN topics AS t ON t.topic_id = mt.topic_id
         WHERE t.offering_id = m.offering_id AND mt.status = 'PUBLISHED') AS materials_total,
        (SELECT COUNT(*) FROM material_completions AS mc
         JOIN materials AS mt ON mt.material_id = mc.material_id
         JOIN topics AS t ON t.topic_id = mt.topic_id
         WHERE mc.student_id = m.user_id AND t.offering_id = m.offering_id
           AND mt.status = 'PUBLISHED') AS materials_done,
        (SELECT COUNT(*) FROM activities AS a
         WHERE a.offering_id = m.offering_id AND a.activity_type = 'ASSIGNMENT'
           AND a.status <> 'DRAFT') AS assignments_total,
        (SELECT COUNT(*) FROM submissions AS s JOIN activities AS a ON a.activity_id = s.assignment_id
         WHERE a.offering_id = m.offering_id AND a.status <> 'DRAFT'
           AND (s.student_id = m.user_id OR s.group_id IN (SELECT gm.group_id FROM group_members AS gm WHERE gm.student_id = m.user_id)) AND s.status = 'SUBMITTED') AS assignments_done,
        (SELECT COUNT(*) FROM activities AS a
         WHERE a.offering_id = m.offering_id AND a.activity_type = 'QUIZ'
           AND a.status <> 'DRAFT') AS quizzes_total,
        (SELECT COUNT(DISTINCT qa.quiz_id) FROM quiz_attempts AS qa
         JOIN activities AS a ON a.activity_id = qa.quiz_id
         WHERE a.offering_id = m.offering_id AND a.status <> 'DRAFT'
           AND qa.student_id = m.user_id AND qa.finalized_by IS NOT NULL) AS quizzes_done
    FROM course_memberships AS m
    JOIN users AS u ON u.user_id = m.user_id
    JOIN students AS st ON st.user_id = m.user_id
    WHERE m.offering_id = %s AND m.status = 'ACTIVE' AND m.course_role = 'STUDENT'"""


class ReportRepository:
    def __init__(self, sql: Sql):
        self.sql = sql

    # ------------------------------------------------------------------ admin
    def admin_classes(
        self, *, q: str | None, semester: str | None, status: str | None, offset: int, limit: int
    ) -> tuple[list[dict[str, Any]], int]:
        where, params = ["1 = 1"], []
        if q:
            where.append("(c.course_code LIKE %s ESCAPE '!' OR o.title LIKE %s ESCAPE '!')")
            params += ["%" + like_literal(q) + "%"] * 2
        if semester:
            where.append("o.semester = %s")
            params.append(semester)
        if status:
            where.append("o.state = %s")
            params.append(status)
        condition = " AND ".join(where)
        source = """FROM course_offerings AS o
            JOIN courses AS c ON c.course_id = o.course_id
            LEFT JOIN course_memberships AS lead_m
                ON lead_m.offering_id = o.offering_id AND lead_m.status = 'ACTIVE'
               AND lead_m.course_role = 'PRIMARY_INSTRUCTOR'
            LEFT JOIN users AS u ON u.user_id = lead_m.user_id"""
        total = self.sql.scalar(f"SELECT COUNT(*) {source} WHERE {condition}", *params)
        rows = self.sql.all(
            f"""SELECT o.offering_id, c.course_code, c.course_name, o.title, o.semester,
                       o.section_code, o.state, u.user_id AS lead_id, u.full_name AS lead_name,
                       (SELECT COUNT(*) FROM course_memberships AS m
                        WHERE m.offering_id = o.offering_id AND m.status = 'ACTIVE'
                          AND m.course_role = 'STUDENT') AS student_count
                {source} WHERE {condition}
                ORDER BY o.semester DESC, c.course_code, o.section_code LIMIT %s, %s""",
            *params,
            offset,
            limit,
        )
        return rows, total

    def audit_entries(
        self,
        *,
        actor_id: int | None,
        action: str | None,
        target_type: str | None,
        offset: int,
        limit: int,
        offering_id: int | None = None,
        from_at=None,
        to_at=None,
    ) -> tuple[list[dict[str, Any]], int]:
        where, params = ["1 = 1"], []
        for column, value in (
            ("e.actor_id", actor_id),
            ("e.action_type", action),
            ("e.target_type", target_type),
        ):
            if value is not None:
                where.append(f"{column} = %s")
                params.append(value)
        if offering_id is not None:
            where.append(
                "((e.target_type='OFFERING' AND e.target_id=%s) OR (e.target_type='MEMBERSHIP' AND e.target_id IN (SELECT membership_id FROM course_memberships WHERE offering_id=%s)))"
            )
            params.extend([offering_id, offering_id])
        for value, operator in ((from_at, ">="), (to_at, "<=")):
            if value is not None:
                from datetime import UTC

                where.append(f"e.created_at {operator} %s")
                params.append(value.astimezone(UTC).replace(tzinfo=None))
        condition = " AND ".join(where)
        total = self.sql.scalar(
            f"SELECT COUNT(*) FROM audit_entries AS e WHERE {condition}", *params
        )
        rows = self.sql.all(
            f"""SELECT e.audit_id, e.actor_id, u.full_name AS actor_name, e.action_type,
                       e.target_type, e.target_id, e.reason, e.details, e.created_at
                FROM audit_entries AS e LEFT JOIN users AS u ON u.user_id = e.actor_id
                WHERE {condition}
                ORDER BY e.created_at DESC, e.audit_id DESC LIMIT %s, %s""",
            *params,
            offset,
            limit,
        )
        return rows, total

    # --------------------------------------------------------------- progress
    def class_progress(self, offering_id: int) -> list[dict[str, Any]]:
        return self.sql.all(f"{_PROGRESS_SELECT} ORDER BY u.full_name, u.user_id", offering_id)

    def student_progress(self, offering_id: int, student_id: int) -> dict[str, Any] | None:
        return self.sql.one(f"{_PROGRESS_SELECT} AND m.user_id = %s", offering_id, student_id)

    # --------------------------------------------------------------- calendar
    def calendar(self, user_id: int, start: datetime, end: datetime) -> list[dict[str, Any]]:
        """Published assignments due, and quizzes open, between start and end, from
        every class the user is in."""
        return self.sql.all(
            """SELECT a.activity_id, a.activity_type, a.title, a.offering_id, c.course_code,
                      o.title AS class_title, m.course_role, x.due_at, q.open_at, q.close_at,
                      CASE WHEN a.activity_type = 'ASSIGNMENT' THEN EXISTS (
                               SELECT 1 FROM submissions AS s WHERE s.assignment_id = a.activity_id
                                 AND (s.student_id = m.user_id OR s.group_id IN (SELECT gm.group_id FROM group_members AS gm WHERE gm.student_id = m.user_id))
                                 AND s.status = 'SUBMITTED')
                           ELSE EXISTS (
                               SELECT 1 FROM quiz_attempts AS qa WHERE qa.quiz_id = a.activity_id
                                 AND qa.student_id = m.user_id AND qa.finalized_by IS NOT NULL)
                      END AS done
               FROM activities AS a
               JOIN course_offerings AS o ON o.offering_id = a.offering_id
               JOIN courses AS c ON c.course_id = o.course_id
               JOIN course_memberships AS m
                   ON m.offering_id = a.offering_id AND m.user_id = %s AND m.status = 'ACTIVE'
               LEFT JOIN assignments AS x ON x.activity_id = a.activity_id
               LEFT JOIN quizzes AS q ON q.activity_id = a.activity_id
               WHERE a.status = 'PUBLISHED' AND o.state <> 'DRAFT'
                 AND ((x.activity_id IS NOT NULL AND x.due_at BETWEEN %s AND %s)
                      OR (q.activity_id IS NOT NULL AND q.close_at >= %s AND q.open_at <= %s))
               ORDER BY COALESCE(x.due_at, q.close_at), a.activity_id""",
            user_id,
            start,
            end,
            start,
            end,
        )
