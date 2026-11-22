"""Personal projections added to the main course, enrollment and content model."""

from datetime import UTC, timedelta

from app.api.schemas.common import utc_payload
from app.core.errors import ApiError
from app.infrastructure.db.repositories.assessment_repository import AssessmentRepository
from app.infrastructure.db.repositories.course_repository import CourseRepository
from app.infrastructure.db.repositories.notification_repository import NotificationRepository
from app.infrastructure.db.sql import Sql, like_literal
from app.services.access import is_teacher, require_member
from app.services.submission_service import _page


class PersonalService:
    def __init__(self, database):
        self.database = database

    @staticmethod
    def _checklist(sql, offering_id, student_id):
        materials = sql.all(
            """SELECT m.material_id AS id,m.title,
            EXISTS (SELECT 1 FROM material_completions c WHERE c.material_id=m.material_id AND c.student_id=%s) AS complete
            FROM materials m JOIN topics t ON t.topic_id=m.topic_id
            WHERE t.offering_id=%s AND m.status='PUBLISHED' AND m.is_mandatory=1 ORDER BY m.material_id""",
            student_id,
            offering_id,
        )
        activities = sql.all(
            """SELECT a.activity_id AS id,a.title,a.activity_type AS kind,
            CASE WHEN a.activity_type='ASSIGNMENT' THEN EXISTS (SELECT 1 FROM submissions s
                WHERE s.assignment_id=a.activity_id AND s.status='SUBMITTED' AND (s.student_id=%s OR EXISTS (
                    SELECT 1 FROM submission_roster r WHERE r.submission_id=s.submission_id AND r.student_id=%s)))
            ELSE EXISTS (SELECT 1 FROM quiz_attempts t WHERE t.quiz_id=a.activity_id AND t.student_id=%s AND t.finalized_by IS NOT NULL AND t.score IS NOT NULL) END AS complete
            FROM activities a WHERE a.offering_id=%s AND a.status='PUBLISHED' AND a.is_mandatory=1 ORDER BY a.activity_id""",
            student_id,
            student_id,
            student_id,
            offering_id,
        )
        items = []
        for row in materials + activities:
            kind = row.get("kind", "MATERIAL")
            href = (
                f"/offerings/{offering_id}/materials"
                if kind == "MATERIAL"
                else f"/{'assignments' if kind == 'ASSIGNMENT' else 'quizzes'}/{row['id']}"
            )
            items.append(
                {
                    "id": f"{kind}:{row['id']}",
                    "kind": kind,
                    "title": row["title"],
                    "complete": bool(row["complete"]),
                    "reason": "Completed" if row["complete"] else "Pending",
                    "href": href,
                }
            )
        return items

    def progress(self, *, actor, offering_id=None, page=1, page_size=25, search=None, state="ALL"):
        with self.database.read_connection() as connection:
            sql = Sql(connection)
            teacher = False
            if offering_id is not None:
                teacher = is_teacher(require_member(CourseRepository(sql), actor, offering_id))
            where = "m.status='ACTIVE' AND m.course_role='STUDENT' AND o.state<>'DRAFT'"
            params = []
            if offering_id is not None:
                where += " AND m.offering_id=%s"
                params.append(offering_id)
            if not teacher:
                where += " AND m.user_id=%s"
                params.append(actor.user_id)
            if search:
                where += " AND u.full_name LIKE %s ESCAPE '!'"
                params.append("%" + like_literal(search) + "%")
            members = sql.all(
                f"""SELECT m.membership_id,m.offering_id,m.user_id,u.full_name FROM course_memberships m
                JOIN users u ON u.user_id=m.user_id JOIN course_offerings o ON o.offering_id=m.offering_id
                WHERE {where} ORDER BY m.offering_id,u.full_name,m.user_id""",
                *params,
            )
            rows = []
            for member in members:
                items = self._checklist(sql, member["offering_id"], member["user_id"])
                total = len(items)
                completed = sum(item["complete"] for item in items)
                if state == "COMPLETE" and (not total or completed != total):
                    continue
                if state == "INCOMPLETE" and completed == total:
                    continue
                rows.append(
                    {
                        "offeringId": member["offering_id"],
                        "membershipId": member["membership_id"],
                        "studentId": member["user_id"],
                        "displayName": member["full_name"],
                        "completed": completed,
                        "total": total,
                        "percent": round(100 * completed / total) if total else None,
                        "notice": None if total else "NO_MANDATORY_ACTIVITIES",
                        "items": items,
                    }
                )
            return {
                "teacher": teacher,
                "rows": _page(
                    rows[(page - 1) * page_size : page * page_size], page, page_size, len(rows)
                ),
            }

    def calendar(
        self, *, actor, offering_id=None, kind=None, start=None, end=None, page=1, page_size=25
    ):
        with self.database.read_connection() as connection:
            sql = Sql(connection)
            now = AssessmentRepository(sql).db_now()
            start = start or now
            end = end or start + timedelta(days=30)
            start = start.astimezone(UTC) if start.tzinfo else start.replace(tzinfo=UTC)
            end = end.astimezone(UTC) if end.tzinfo else end.replace(tzinfo=UTC)
            if start >= end or end - start > timedelta(days=366):
                raise ApiError(400, "INVALID_DATE_RANGE", "End must be after start.")
            if actor.role == "ADMIN":
                return utc_payload({**_page([], page, page_size, 0), "serverNow": now})
            rows = sql.all(
                """SELECT a.activity_id,a.offering_id,a.title,a.activity_type,o.title AS section,
                x.due_at,x.cutoff_at,q.open_at,q.close_at
                FROM activities a JOIN course_offerings o ON o.offering_id=a.offering_id
                JOIN course_memberships m ON m.offering_id=o.offering_id AND m.user_id=%s AND m.status='ACTIVE'
                LEFT JOIN assignments x ON x.activity_id=a.activity_id LEFT JOIN quizzes q ON q.activity_id=a.activity_id
                WHERE o.state='OPEN' AND a.status='PUBLISHED' ORDER BY a.activity_id""",
                actor.user_id,
            )
            items = []
            for row in rows:
                if offering_id is not None and row["offering_id"] != offering_id:
                    continue
                events = (
                    [("ASSIGNMENT_DUE", row["due_at"])]
                    if row["activity_type"] == "ASSIGNMENT"
                    else [("QUIZ_OPEN", row["open_at"]), ("QUIZ_CLOSE", row["close_at"])]
                )
                for event, at in events:
                    if (kind is None or kind == event) and start <= at < end:
                        items.append(
                            {
                                "id": f"{event}:{row['activity_id']}",
                                "offeringId": row["offering_id"],
                                "activityId": row["activity_id"],
                                "title": row["title"],
                                "section": row["section"],
                                "kind": event,
                                "at": at,
                                "opensAt": row["open_at"],
                                "endsAt": row["cutoff_at"] or row["close_at"],
                                "status": "PUBLISHED",
                                "targetUri": f"/{'assignments' if row['activity_type'] == 'ASSIGNMENT' else 'quizzes'}/{row['activity_id']}",
                            }
                        )
            items.sort(key=lambda x: (x["at"], x["id"]))
            return utc_payload(
                {
                    **_page(
                        items[(page - 1) * page_size : page * page_size],
                        page,
                        page_size,
                        len(items),
                    ),
                    "serverNow": now,
                }
            )

    def dashboard(self, actor, base):
        from app.services.course_service import CourseService

        now = base["serverNow"]
        base.update(progress=[], tasks=[], announcements=[], unread=0, upcoming=[])
        with self.database.read_connection() as connection:
            sql = Sql(connection)
            base["unread"] = NotificationRepository(sql).inbox(
                actor.user_id, unread_only=False, offset=0, limit=0
            )[2]
            if actor.role == "ADMIN":
                base["counts"]["pendingRegistrations"] = sql.scalar(
                    "SELECT COUNT(*) FROM course_registrations WHERE status='PENDING'"
                )
                base["counts"]["archivedLeadRepairs"] = sql.scalar(
                    "SELECT COUNT(*) FROM course_offerings o WHERE o.state='ARCHIVED' AND NOT EXISTS (SELECT 1 FROM course_memberships m JOIN users u ON u.user_id=m.user_id WHERE m.offering_id=o.offering_id AND m.course_role='PRIMARY_INSTRUCTOR' AND m.status='ACTIVE' AND u.status='ACTIVE')"
                )
                return utc_payload(base)
            for item in base["assignments"]:
                if actor.role == "STUDENT" and not item["submitted"] and item["cutoffAt"] >= now:
                    base["tasks"].append(
                        {
                            "id": f"assignment:{item['id']}",
                            "kind": "ASSIGNMENT",
                            "title": item["title"],
                            "detail": "Submission pending",
                            "at": item["dueAt"],
                            "href": f"/assignments/{item['id']}",
                        }
                    )
                if actor.role == "INSTRUCTOR" and item["cutoffAt"] < now:
                    pending = sql.scalar(
                        """SELECT COUNT(DISTINCT IF(x.is_group_work,CONCAT('g',gm.group_id),CONCAT('s',m.user_id)))
                        FROM assignments x JOIN activities a ON a.activity_id=x.activity_id
                        JOIN course_memberships m ON m.offering_id=a.offering_id AND m.course_role='STUDENT' AND m.status='ACTIVE'
                        LEFT JOIN group_members gm ON gm.student_id=m.user_id AND gm.assignment_id=a.activity_id
                        LEFT JOIN submissions s ON s.assignment_id=a.activity_id AND (IF(x.is_group_work,s.group_id=gm.group_id,s.student_id=m.user_id))
                        LEFT JOIN grades g ON g.submission_id=s.submission_id
                        WHERE a.activity_id=%s AND (g.grade_id IS NULL OR g.published_revision_no IS NULL OR g.draft_revision_no<>g.published_revision_no)""",
                        item["id"],
                    )
                    if pending:
                        base["tasks"].append(
                            {
                                "id": f"grading:{item['id']}",
                                "kind": "GRADING",
                                "title": item["title"],
                                "detail": f"{pending} awaiting grading or publication",
                                "href": f"/assignments/{item['id']}/grading",
                            }
                        )
            quizzes = sql.all(
                "SELECT a.activity_id,a.title,q.close_at FROM activities a JOIN quizzes q ON q.activity_id=a.activity_id JOIN course_memberships m ON m.offering_id=a.offering_id JOIN course_offerings o ON o.offering_id=a.offering_id WHERE o.state='OPEN' AND m.user_id=%s AND m.status='ACTIVE' AND a.status='PUBLISHED' AND q.close_at>UTC_TIMESTAMP(6) AND (q.max_attempts=0 OR (SELECT COUNT(*) FROM quiz_attempts t WHERE t.quiz_id=a.activity_id AND t.student_id=%s)<q.max_attempts)",
                actor.user_id,
                actor.user_id,
            )
            base["counts"]["pendingQuizzes"] = len(quizzes) if actor.role == "STUDENT" else None
            if actor.role == "STUDENT":
                for q in quizzes:
                    base["tasks"].append(
                        {
                            "id": f"quiz:{q['activity_id']}",
                            "kind": "QUIZ",
                            "title": q["title"],
                            "detail": "Quiz available",
                            "at": q["close_at"],
                            "href": f"/quizzes/{q['activity_id']}",
                        }
                    )
            announcements = sql.all(
                "SELECT n.announcement_id,n.offering_id,n.title FROM announcements n JOIN course_memberships m ON m.offering_id=n.offering_id JOIN course_offerings o ON o.offering_id=n.offering_id WHERE m.user_id=%s AND m.status='ACTIVE' AND n.status='PUBLISHED' AND n.published_at IS NOT NULL AND o.state='OPEN' ORDER BY n.published_at DESC,n.announcement_id DESC LIMIT 5",
                actor.user_id,
            )
            base["announcements"] = [
                {
                    "id": a["announcement_id"],
                    "title": a["title"],
                    "offeringId": a["offering_id"],
                    "href": f"/offerings/{a['offering_id']}/announcements",
                }
                for a in announcements
            ]
        base["sections"] = [
            CourseService(self.database).get_offering(actor=actor, offering_id=s["id"])
            for s in base["sections"]
        ]
        base["upcoming"] = self.calendar(
            actor=actor, start=now, end=now + timedelta(days=7), page_size=100
        )["items"]
        if actor.role == "STUDENT":
            base["progress"] = self.progress(actor=actor, page_size=100)["rows"]["items"]
        return utc_payload(base)
