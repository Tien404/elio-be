"""Manual grading of assignments (class diagram: GradingService).

The professor types a score (0..max) or a special mark (11 absent / 12 banned, both 0)
plus optional feedback per assignment. Each save is a draft revision that students
cannot see; releaseGrades makes every draft of one assignment visible to the class.
Students and the professor see the same grade report page.
"""

import csv
import io
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.api.schemas.common import utc_payload
from app.core.errors import ApiError, conflict, forbidden, not_found, version_conflict
from app.domain.context import Actor
from app.domain.entities import Grade, SpecialMark
from app.infrastructure.db.repositories.assessment_repository import AssessmentRepository
from app.infrastructure.db.repositories.audit_repository import AuditRepository
from app.infrastructure.db.repositories.course_repository import CourseRepository
from app.infrastructure.db.repositories.grading_repository import GradingRepository
from app.infrastructure.db.repositories.group_repository import GroupRepository
from app.infrastructure.db.repositories.quiz_repository import QuizRepository
from app.infrastructure.db.sql import Sql
from app.services.access import is_teacher, require_member, require_teacher
from app.services.notification_service import notify_course
from app.services.quiz_service import finish_expired, quiz_from_row

CENT = Decimal("0.01")


def _money(value: Decimal) -> float:
    return float(value.quantize(CENT, rounding=ROUND_HALF_UP))


def grade_item(row: dict[str, Any], *, teacher: bool) -> dict[str, Any]:
    """One grade-report row. The professor sees the current draft, students the released one."""
    if teacher:
        score, mark, feedback = row["draft_score"], row["draft_mark"], row["draft_feedback"]
    else:
        score, mark, feedback = (
            row["released_score"],
            row["released_mark"],
            row["released_feedback"],
        )
    if row["grade_id"] is None or (not teacher and row["published_revision_no"] is None):
        status = "NOT_GRADED"
    elif row["draft_revision_no"] == row["published_revision_no"]:
        status = "RELEASED"
    else:
        status = "DRAFT" if teacher else "RELEASED"  # students only ever see released grades
    max_score = Decimal(row["max_score"])
    weight = Decimal(row["weight_pct"])
    percentage = contribution = None
    if score is not None:
        percentage = _money(score / max_score * 100)
        if weight > 0:
            contribution = _money(score / max_score * weight)
    special = SpecialMark(mark) if mark else None
    return {
        "activityId": row["activity_id"],
        "type": "ASSIGNMENT",
        "title": row["title"],
        "weight": float(weight) if weight > 0 else None,
        "grade": None if score is None else _money(score),
        "specialMark": special.value if special else None,
        "specialCode": special.code if special else None,
        "rangeMin": 0.0,
        "rangeMax": float(max_score),
        "percentage": percentage,
        "feedback": feedback,
        "contribution": contribution,
        "state": (
            "CORRECTION_DRAFT"
            if row["published_revision_no"] is not None
            and row["draft_revision_no"] != row["published_revision_no"]
            else "DRAFT"
        )
        if teacher and status == "DRAFT"
        else "PUBLISHED"
        if status == "RELEASED"
        else "SUBMITTED"
        if row["submission_status"] == "SUBMITTED"
        else "NOT_SUBMITTED",
        "status": status,
        "submitted": row["submission_status"] == "SUBMITTED",
        "submissionId": row["submission_id"],
        "gradeId": row["grade_id"],
        "groupId": row["group_id"],
    }


def quiz_item(row: dict[str, Any]) -> dict[str, Any]:
    """A quiz row: graded automatically, the same for student and professor."""
    score = quiz_from_row(row).counted_score([Decimal(s) for s in row["scores"]])
    max_score = Decimal(row["max_score"])
    weight = Decimal(row["weight_pct"])
    return {
        "activityId": row["activity_id"],
        "type": "QUIZ",
        "title": row["title"],
        "weight": float(weight) if weight > 0 else None,
        "grade": None if score is None else _money(score),
        "specialMark": None,
        "specialCode": None,
        "rangeMin": 0.0,
        "rangeMax": float(max_score),
        "percentage": None if score is None else _money(score / max_score * 100),
        "feedback": None,
        "contribution": None
        if score is None or weight <= 0
        else _money(score / max_score * weight),
        "status": "NOT_GRADED" if score is None else "RELEASED",
        "state": "PUBLISHED" if score is not None else row.get("state", "NOT_STARTED"),
        "submitted": bool(row["scores"]),
        "submissionId": None,
        "gradeId": None,
        "groupId": None,
    }


def _student(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["user_id"],
        "displayName": row["full_name"],
        "studentCode": row["student_code"],
    }


def _revision_view(row: dict[str, Any]) -> dict[str, Any]:
    special = SpecialMark(row["special_mark"]) if row["special_mark"] else None
    return {
        "revisionNo": row["revision_no"],
        "sourceVersionNo": row["source_version_no"],
        "reason": row["reason"],
        "zeroReason": row["zero_reason"],
        "isMissingZero": bool(row["is_missing_zero"]),
        "grade": _money(row["score"]),
        "specialMark": special.value if special else None,
        "specialCode": special.code if special else None,
        "feedback": row["feedback"],
        "revisedBy": {"id": row["revised_by"], "displayName": row["revised_by_name"]},
        "revisedAt": row["revised_at"],
    }


def _csv_grade(item: dict[str, Any]):
    if item["specialCode"]:
        return item["specialCode"]
    return "" if item["grade"] is None else item["grade"]


def _safe_cell(text: str) -> str:
    """Stop spreadsheet apps from running a cell that starts like a formula."""
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


def course_total(items: list[dict[str, Any]]) -> dict[str, Any]:
    weight = sum((Decimal(str(i.get("weight") or 0)) for i in items), Decimal(0))
    available = sum(
        (Decimal(str(i.get("weight") or 0)) for i in items if i["grade"] is not None), Decimal(0)
    )
    valid = weight == 100
    total = (
        sum(
            (
                Decimal(str(i["grade"]))
                / Decimal(str(i["rangeMax"]))
                * Decimal(str(i.get("weight") or 0))
                / 10
                for i in items
                if i["grade"] is not None
            ),
            Decimal(0),
        )
        if valid and any(i["grade"] is not None for i in items)
        else None
    )
    return {
        "rangeMin": 0.0,
        "rangeMax": 10.0,
        "grade": _money(total) if total is not None else None,
        "percentage": _money(total * 10) if total is not None else None,
        "final": valid and bool(items) and all(i["grade"] is not None for i in items),
        "totalWeight": float(weight),
        "availableWeight": float(available),
    }


class GradingService:
    def __init__(self, database=None):
        self.database = database

    # --------------------------------------------------------------- reading
    def get_my_grades(self, *, actor: Actor) -> dict[str, Any]:
        """getMyGrades: the student's grade report for each of their classes."""
        with self.database.transaction() as connection:
            sql = Sql(connection)
            return {
                "items": [
                    self._report(sql, offering_id, actor.user_id, teacher=False)
                    for offering_id in GradingRepository(sql).my_class_ids(actor.user_id)
                ]
            }

    def get_student_grades(
        self, *, actor: Actor, offering_id: int, student_id: int
    ) -> dict[str, Any]:
        """getStudentGrades: the professor opens a student's page (with drafts);
        a student may open only their own page (released grades only)."""
        with self.database.transaction() as connection:
            sql = Sql(connection)
            member = require_member(CourseRepository(sql), actor, offering_id)
            teacher = is_teacher(member)
            if not teacher and actor.user_id != student_id:
                raise not_found("Student")
            return self._report(sql, offering_id, student_id, teacher=teacher)

    def get_gradebook(
        self, *, actor: Actor, offering_id: int, search=None, state="ALL", activity_id=None
    ) -> dict[str, Any]:
        """getCourseGradebook: every student x every grade item of the class (the
        professor's current values, drafts included)."""
        with self.database.transaction() as connection:
            return self._filter_gradebook(
                self._gradebook(Sql(connection), actor, offering_id), search, state, activity_id
            )

    def export_gradebook_csv(
        self, *, actor: Actor, offering_id: int, search=None, state="ALL", activity_id=None
    ) -> tuple[str, str]:
        """exportGradebookCsv: the gradebook as CSV. Returns (file name, text).
        Special grades are written as their school codes 11 / 12."""
        with self.database.transaction() as connection:
            book = self._filter_gradebook(
                self._gradebook(Sql(connection), actor, offering_id), search, state, activity_id
            )
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(
            ["Student code", "Name"]
            + [f"{c['title']} (/{c['rangeMax']:g})" for c in book["columns"]]
            + [f"Total (/{book['total']['rangeMax']:g})", "Percentage"]
        )
        for row in book["rows"]:
            cells = [_csv_grade(i) for i in row["items"]]
            total = row["total"]
            writer.writerow(
                [
                    _safe_cell(row["student"]["studentCode"]),
                    _safe_cell(row["student"]["displayName"]),
                ]
                + cells
                + [
                    "" if total["grade"] is None else total["grade"],
                    "" if total["percentage"] is None else total["percentage"],
                ]
            )
        name = f"{book['courseCode']}-{book['sectionCode']}-{book['semester']}-grades.csv"
        return name, out.getvalue()

    @staticmethod
    def _filter_gradebook(book, search, state, activity_id):
        book["rows"] = [
            row
            for row in book["rows"]
            if (not search or search.lower() in row["student"]["displayName"].lower())
            and (state == "ALL" or row["total"]["final"] == (state == "FINAL"))
        ]
        if activity_id is not None:
            book["columns"] = [c for c in book["columns"] if c["activityId"] == activity_id]
            for row in book["rows"]:
                row["items"] = [item for item in row["items"] if item["activityId"] == activity_id]
        return book

    def update_weights(self, *, actor, offering_id, expected_version, values):
        with self.database.transaction() as connection:
            sql = Sql(connection)
            require_teacher(CourseRepository(sql), actor, offering_id)
            offering = CourseRepository(sql).get_offering(offering_id, lock=True)
            if offering.version != expected_version:
                raise version_conflict(offering.version)
            current = sql.all(
                "SELECT activity_id,activity_type FROM activities WHERE offering_id=%s AND status='PUBLISHED'",
                offering_id,
            )
            keys = {(r["activity_id"], r["activity_type"]) for r in current}
            if len(values) != len(keys) or {(v["id"], v["kind"]) for v in values} != keys:
                raise ApiError(
                    422, "WEIGHT_SET_MISMATCH", "Provide each published activity exactly once."
                )
            if sum((Decimal(str(v["weight"])) for v in values), Decimal(0)) != 100:
                raise ApiError(422, "INVALID_WEIGHT_TOTAL", "Weights must sum to 100.")
            for value in values:
                sql.execute(
                    "UPDATE activities SET weight_pct=%s,version=version+1 WHERE activity_id=%s",
                    value["weight"],
                    value["id"],
                )
            sql.execute(
                "UPDATE course_offerings SET version=version+1 WHERE offering_id=%s", offering_id
            )

    def _gradebook(self, sql: Sql, actor: Actor, offering_id: int) -> dict[str, Any]:
        if not is_teacher(require_member(CourseRepository(sql), actor, offering_id)):
            raise forbidden()
        offering = CourseRepository(sql).offering_summary(offering_id)
        columns = [
            {k: item[k] for k in ("activityId", "type", "title", "rangeMax", "weight")}
            for item in self._items(sql, offering_id, 0, teacher=True)  # 0 = nobody's work
        ]
        rows = []
        for student in GradingRepository(sql).class_students(offering_id):
            items = self._items(sql, offering_id, student["user_id"], teacher=False)
            private_items = self._items(sql, offering_id, student["user_id"], teacher=True)
            for item in items:
                item["state"] = next(
                    (i["state"] for i in private_items if i["activityId"] == item["activityId"]),
                    item["state"],
                )
            rows.append(
                {"student": _student(student), "items": items, "total": course_total(items)}
            )
        return {
            "offeringId": offering_id,
            "courseCode": offering["course_code"],
            "title": offering["title"],
            "semester": offering["semester"],
            "sectionCode": offering["section_code"],
            "version": offering["version"],
            "writable": offering["state"] != "ARCHIVED",
            "serverNow": AssessmentRepository(sql).db_now(),
            "columns": columns,
            "total": course_total(
                [{"rangeMax": c["rangeMax"], "grade": None, "weight": c["weight"]} for c in columns]
            ),
            "rows": rows,
        }

    def _report(self, sql: Sql, offering_id: int, student_id: int, *, teacher: bool):
        student = GradingRepository(sql).find_student(offering_id, student_id)
        if student is None:
            raise not_found("Student")
        offering = CourseRepository(sql).offering_summary(offering_id)
        items = self._items(sql, offering_id, student_id, teacher=teacher)
        return {
            "offeringId": offering_id,
            "courseCode": offering["course_code"],
            "title": offering["title"],
            "student": _student(student),
            "items": items,
            "total": course_total(items),
        }

    @staticmethod
    def _items(sql: Sql, offering_id: int, student_id: int, *, teacher: bool) -> list:
        """Grade-page rows (assignments and quizzes) in date order."""
        finish_expired(sql, offering_id=offering_id, student_id=student_id)
        dated = [
            (r["due_at"], r["activity_id"], grade_item(r, teacher=teacher))
            for r in GradingRepository(sql).report_rows(offering_id, student_id)
        ] + [
            (q["close_at"], q["activity_id"], quiz_item(q))
            for q in QuizRepository(sql).quiz_grade_rows(offering_id, student_id)
        ]
        return [item for _, _, item in sorted(dated, key=lambda d: (d[0], d[1]))]

    # --------------------------------------------------------------- writing
    def save_draft(
        self,
        *,
        actor: Actor,
        submission_id: int,
        score: Decimal | None,
        special_mark: SpecialMark | None,
        feedback: str | None,
        expected_submission_version: int,
        source_version_no: int | None,
        expected_grade_version: int | None = None,
        reason: str | None = None,
        zero_reason: str | None = None,
    ) -> dict[str, Any]:
        """saveDraft: grade one submission. Students see it after releaseGrades."""
        with self.database.transaction() as connection:
            sql = Sql(connection)
            assessments = AssessmentRepository(sql)
            submission = assessments.get_submission(submission_id)
            if submission is None:
                raise not_found("Submission")
            assignment = assessments.get_assignment(submission["assignment_id"])
            require_teacher(CourseRepository(sql), actor, assignment["offering_id"])
            stream = assessments.lock_submission_by_id(submission_id)
            self._write(
                sql,
                actor,
                assignment,
                stream,
                score,
                special_mark,
                feedback,
                expected_submission_version=expected_submission_version,
                source_version_no=source_version_no,
                expected_grade_version=expected_grade_version,
                reason=reason,
                zero_reason=zero_reason,
            )
            # the row as seen by (one of) the submission's students
            grade = GradingRepository(sql).lock_grade(stream["submission_id"])
            return self._record(sql, actor, grade["grade_id"])

    def record_missing_work(
        self,
        *,
        actor: Actor,
        assignment_id: int,
        student_id: int,
        special_mark: SpecialMark | None,
        feedback: str | None,
        zero_reason: str,
    ) -> dict[str, Any]:
        """confirmMissingWork: give a student who did not submit a special mark (11/12)."""
        with self.database.transaction() as connection:
            sql = Sql(connection)
            assessments = AssessmentRepository(sql)
            assignment = assessments.get_assignment(assignment_id)
            if assignment is None:
                raise not_found("Assignment")
            require_teacher(CourseRepository(sql), actor, assignment["offering_id"])
            if assignment["status"] == "DRAFT":
                raise conflict("ASSIGNMENT_NOT_PUBLISHED", "Publish the assignment first.")
            if GradingRepository(sql).find_student(assignment["offering_id"], student_id) is None:
                raise not_found("Student")
            groups = GroupRepository(sql)
            group_id = (
                groups.group_of(assignment_id, student_id) if assignment["is_group_work"] else None
            )
            if assignment["is_group_work"] and group_id is None:
                raise conflict(
                    "GROUP_REQUIRED",
                    "Place this student in a group before recording a group grade.",
                )
            if group_id is not None:  # group work: the mark goes to the whole group
                stream = groups.lock_group_submission(group_id)
                if stream is None:
                    groups.insert_group_submission(assignment_id, group_id)
                    stream = groups.lock_group_submission(group_id)
            else:
                stream = assessments.lock_submission(
                    assignment_id=assignment_id, student_id=student_id
                )
                if stream is None:  # an empty "not submitted" record to hang the grade on
                    assessments.insert_submission(
                        assignment_id=assignment_id, student_id=student_id
                    )
                    stream = assessments.lock_submission(
                        assignment_id=assignment_id, student_id=student_id
                    )
            if stream["status"] == "SUBMITTED":
                raise conflict("ALREADY_SUBMITTED", "This student submitted; grade the submission.")
            self._write(
                sql,
                actor,
                assignment,
                stream,
                None if special_mark else Decimal(0),
                special_mark,
                feedback,
                expected_submission_version=0,
                source_version_no=None,
                zero_reason=zero_reason,
            )
            grade = GradingRepository(sql).lock_grade(stream["submission_id"])
            return self._record(sql, actor, grade["grade_id"])

    def release_grades(self, *, actor: Actor, assignment_id: int) -> dict[str, Any]:
        """releaseGrades: every grade saved for the assignment becomes visible to students."""
        with self.database.transaction() as connection:
            sql = Sql(connection)
            assignment = AssessmentRepository(sql).get_assignment(assignment_id, lock=True)
            if assignment is None:
                raise not_found("Assignment")
            require_teacher(CourseRepository(sql), actor, assignment["offering_id"])
            repo = GradingRepository(sql)
            self._grading_open(sql, assignment)
            students = repo.unreleased_students(assignment_id)
            released = repo.release(assignment_id)
            notify_course(
                sql,
                offering_id=assignment["offering_id"],
                actor_id=actor.user_id,
                event_type="GRADES_RELEASED",
                title=assignment["title"],
                target_type="ASSIGNMENT",
                target_id=assignment_id,
                event_key=f"GRADES_RELEASED:{assignment_id}:{AssessmentRepository(sql).db_now().isoformat()}",
                recipients=students,
            )
            AuditRepository(sql).record(
                actor_id=actor.user_id,
                action="GRADES_RELEASED",
                target_type="ASSIGNMENT",
                target_id=assignment_id,
                details={"released": released},
            )
            return {"assignmentId": assignment_id, "released": released}

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _grading_open(sql, assignment):
        offering = CourseRepository(sql).get_offering(assignment["offering_id"], lock=True)
        if offering.state != "OPEN":
            raise conflict("CLASS_READ_ONLY", "Grading requires an open class.")
        assignment = AssessmentRepository(sql).get_assignment(assignment["activity_id"], lock=True)
        if assignment["status"] != "PUBLISHED":
            raise conflict("ASSIGNMENT_READ_ONLY", "Only published assignments can be graded.")
        if AssessmentRepository(sql).db_now() <= assignment["cutoff_at"]:
            raise conflict("GRADING_NOT_OPEN", "Grading opens after cutoff.")

    @staticmethod
    def _write(
        sql,
        actor,
        assignment,
        stream,
        score,
        special_mark,
        feedback,
        *,
        expected_submission_version,
        source_version_no,
        expected_grade_version=None,
        reason=None,
        zero_reason=None,
    ) -> None:
        stream = AssessmentRepository(sql).get_submission(stream["submission_id"])
        GradingService._grading_open(sql, assignment)
        if stream["version"] != expected_submission_version:
            raise version_conflict(stream["version"])
        if source_version_no != (stream["version"] if stream["status"] == "SUBMITTED" else None):
            raise conflict("INVALID_SOURCE_VERSION", "Review the latest submission before grading.")
        if stream["status"] != "SUBMITTED" and not (zero_reason or "").strip():
            raise ApiError(
                422, "MISSING_ZERO_REASON_REQUIRED", "Provide a reason for missing work."
            )
        if (
            stream["group_id"]
            and stream["status"] != "SUBMITTED"
            and not sql.scalar(
                "SELECT COUNT(*) FROM submission_roster WHERE submission_id=%s",
                stream["submission_id"],
            )
        ):
            GroupRepository(sql).freeze_roster(stream["submission_id"], stream["group_id"])
        submitted = stream["status"] == "SUBMITTED"
        try:
            stored = Grade.check(
                score=score,
                special_mark=special_mark,
                max_score=Decimal(assignment["max_score"]),
                submitted=submitted,
            )
        except ValueError as error:
            raise ApiError(422, "INVALID_GRADE", str(error)) from None
        repo = GradingRepository(sql)
        grade = repo.lock_grade(stream["submission_id"])
        if grade and expected_grade_version is None:
            raise conflict("GRADE_EXISTS", "Open the existing grade before editing.")
        if grade and grade["version"] != expected_grade_version:
            raise version_conflict(grade["version"])
        if grade and grade["published_revision_no"] is not None and not (reason or "").strip():
            raise ApiError(
                400,
                "CORRECTION_REASON_REQUIRED",
                "Provide a reason for changing a published grade.",
            )
        grade_id = grade["grade_id"] if grade else repo.insert_grade(stream["submission_id"])
        repo.add_revision(
            grade_id=grade_id,
            submission_id=stream["submission_id"],
            source_version_no=stream["version"] if submitted else None,
            score=stored,
            special_mark=special_mark.value if special_mark else None,
            feedback=(feedback or "").strip() or None,
            revised_by=actor.user_id,
            reason=reason,
            zero_reason=zero_reason,
        )
        AuditRepository(sql).record(  # never the score or feedback (audit rule)
            actor_id=actor.user_id,
            action="GRADE_SAVED",
            target_type="SUBMISSION",
            target_id=stream["submission_id"],
        )

    @staticmethod
    def _item(sql, assignment, student_id) -> dict[str, Any]:
        rows = GradingRepository(sql).report_rows(
            assignment["offering_id"], student_id, assignment_id=assignment["activity_id"]
        )
        return grade_item(rows[0], teacher=True)

    # ------------------------------------------------------------ grade records
    def list_assignment_grade_records(self, *, actor: Actor, assignment_id: int):
        """Class professor: every student's grade box for one assignment."""
        with self.database.transaction() as connection:
            sql = Sql(connection)
            assignment = AssessmentRepository(sql).get_assignment(assignment_id)
            if assignment is None:
                raise not_found("Assignment")
            member = require_member(CourseRepository(sql), actor, assignment["offering_id"])
            if not is_teacher(member):
                raise forbidden()
            subjects = []
            assessments = AssessmentRepository(sql)
            if assignment["is_group_work"]:
                owners = [
                    (
                        g["group_id"],
                        g["name"],
                        [m["user_id"] for m in g["members"]],
                        assessments.find_group_submission(g["group_id"]),
                    )
                    for g in GroupRepository(sql).list_groups(assignment_id)
                ]
            else:
                owners = [
                    (
                        student["user_id"],
                        student["full_name"],
                        [student["user_id"]],
                        assessments.find_submission(
                            assignment_id=assignment_id, student_id=student["user_id"]
                        ),
                    )
                    for student in GradingRepository(sql).class_students(assignment["offering_id"])
                ]
            from app.infrastructure.db.repositories.identity_repository import IdentityRepository
            from app.services.auth_service import account_view
            from app.services.submission_service import SubmissionService

            for subject_id, label, recipients, submission in owners:
                record = (
                    GradingRepository(sql).lock_grade(submission["submission_id"])
                    if submission
                    else None
                )
                subjects.append(
                    {
                        "subjectId": subject_id,
                        "label": label,
                        "recipients": [
                            account_view(IdentityRepository(sql).get_account(i))["account"]
                            for i in recipients
                        ],
                        "submission": SubmissionService._view(sql, submission)
                        if submission
                        else None,
                        "grade": self._record(sql, actor, record["grade_id"]) if record else None,
                    }
                )
            return {
                "subjects": subjects,
                "serverNow": assessments.db_now(),
                "canGrade": CourseRepository(sql).get_offering(assignment["offering_id"]).state
                == "OPEN"
                and assignment["status"] == "PUBLISHED"
                and assessments.db_now() > assignment["cutoff_at"],
                "subjectType": "GROUP" if assignment["is_group_work"] else "STUDENT",
                "assignmentId": assignment_id,
                "title": assignment["title"],
                "maxScore": float(assignment["max_score"]),
                "items": [
                    {"student": _student(s), "grade": self._item(sql, assignment, s["user_id"])}
                    for s in GradingRepository(sql).class_students(assignment["offering_id"])
                ],
            }

    def get_grade_record(self, *, actor: Actor, grade_record_id: int):
        """The professor sees the draft, the released version and the edit history;
        the grade's student sees only the released version."""
        with self.database.transaction() as connection:
            return self._record(Sql(connection), actor, grade_record_id)

    def revise(
        self,
        *,
        actor: Actor,
        grade_record_id: int,
        score,
        special_mark,
        feedback,
        expected_version,
        expected_submission_version,
        source_version_no,
        reason=None,
        zero_reason=None,
    ):
        """createGradeRevision: change a grade (same rules as saveDraft); a new draft."""
        with self.database.transaction() as connection:
            grade = GradingRepository(Sql(connection)).get_grade(grade_record_id)
        if grade is None:
            raise not_found("Grade")
        self.save_draft(
            actor=actor,
            submission_id=grade["submission_id"],
            score=score,
            special_mark=special_mark,
            feedback=feedback,
            expected_submission_version=expected_submission_version,
            source_version_no=source_version_no,
            expected_grade_version=expected_version,
            reason=reason,
            zero_reason=zero_reason,
        )
        return self.get_grade_record(actor=actor, grade_record_id=grade_record_id)

    def publish(
        self, *, actor: Actor, grade_record_id: int, expected_version: int, revision_no: int
    ):
        """publishGradeRevision: release this one student's (or group's) grade now,
        without waiting for releaseGrades on the whole assignment."""
        with self.database.transaction() as connection:
            sql = Sql(connection)
            repo = GradingRepository(sql)
            grade = repo.get_grade(grade_record_id)
            if grade is None:
                raise not_found("Grade")
            require_teacher(CourseRepository(sql), actor, grade["offering_id"])
            assignment = AssessmentRepository(sql).get_assignment(grade["assignment_id"], lock=True)
            self._grading_open(sql, assignment)
            grade.update(repo.lock_grade(grade["submission_id"]))
            if grade["version"] != expected_version:
                raise version_conflict(grade["version"])
            if grade["draft_revision_no"] != revision_no:
                raise conflict(
                    "DRAFT_REVISION_REQUIRED", "Review the current draft before publishing."
                )
            if repo.release_one(grade_record_id):
                notify_course(
                    sql,
                    offering_id=grade["offering_id"],
                    actor_id=actor.user_id,
                    event_type="GRADES_RELEASED",
                    title=grade["title"],
                    target_type="ASSIGNMENT",
                    target_id=grade["assignment_id"],
                    event_key=f"GRADE_RELEASED:{grade_record_id}:{grade['draft_revision_no']}",
                    recipients=GroupRepository(sql).submission_members(grade["submission_id"]),
                )
                AuditRepository(sql).record(
                    actor_id=actor.user_id,
                    action="GRADE_RELEASED",
                    target_type="GRADE",
                    target_id=grade_record_id,
                )
            return self._record(sql, actor, grade_record_id)

    def _record(self, sql: Sql, actor: Actor, grade_id: int) -> dict[str, Any]:
        repo = GradingRepository(sql)
        grade = repo.get_grade(grade_id)
        if grade is None:
            raise not_found("Grade")
        member = require_member(CourseRepository(sql), actor, grade["offering_id"])
        teacher = is_teacher(member)
        students = GroupRepository(sql).submission_members(grade["submission_id"])
        if not teacher and (
            actor.user_id not in students or grade["published_revision_no"] is None
        ):
            raise not_found("Grade")
        revisions = {r["revision_no"]: r for r in repo.revisions(grade_id)}
        released = revisions.get(grade["published_revision_no"])
        draft = revisions.get(grade["draft_revision_no"])
        assignment = AssessmentRepository(sql).get_assignment(grade["assignment_id"])
        item_rows = repo.report_rows(
            grade["offering_id"], students[0], assignment_id=assignment["activity_id"]
        )
        item = grade_item(item_rows[0], teacher=teacher)
        publication = _revision_view(released) if released else None
        if publication and not teacher:
            publication["reason"] = None  # correction audit reasons remain teacher-private
        return utc_payload(
            {
                **item,
                "id": grade_id,
                "submissionId": grade["submission_id"],
                "assignmentId": grade["assignment_id"],
                "publishedAt": grade["published_at"],
                "studentIds": students,
                "status": "RELEASED"
                if not teacher or grade["draft_revision_no"] == grade["published_revision_no"]
                else "DRAFT",
                "current": _revision_view(draft) if teacher else publication,
                "draftRevision": _revision_view(draft) if teacher else None,
                "publishedRevision": publication,
                "released": publication,
                "revisions": [_revision_view(r) for r in revisions.values()] if teacher else None,
                "version": grade["version"] if teacher else grade["published_revision_no"],
            }
        )

    # ------------------------------------------- contract operations not used
