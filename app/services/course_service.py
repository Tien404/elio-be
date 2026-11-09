import re
import secrets
import string
from decimal import Decimal
from typing import Any

from app.core.errors import (
    ApiError,
    FeatureNotImplemented,
    conflict,
    forbidden,
    not_found,
    version_conflict,
)
from app.domain.context import Actor
from app.domain.entities import (
    Course,
    CourseMembership,
    CourseOffering,
    CourseRegistration,
    CourseRole,
    DegreeLevel,
    SystemRole,
)
from app.infrastructure.db.repositories.audit_repository import AuditRepository
from app.infrastructure.db.repositories.course_repository import (
    _OFFERING_SUMMARY_SELECT,
    CourseRepository,
    course_from_row,
    membership_from_row,
    offering_from_row,
    registration_from_row,
)
from app.infrastructure.db.repositories.identity_repository import (
    IdentityRepository,
    user_from_row,
)
from app.infrastructure.db.sql import Sql, is_unique_violation
from app.services.auth_service import normalize_email


def course_view(course: Course) -> dict[str, Any]:
    """CatalogCourse response shape."""
    return {
        "id": course.course_id,
        "courseCode": course.course_code,
        "courseName": course.course_name,
        "credits": float(course.credits),
    }


def offering_view(
    offering: CourseOffering, course_code: str, lead_membership_id: int
) -> dict[str, Any]:
    """Offering response shape (OpenAPI contract)."""
    return {
        "id": offering.offering_id,
        "courseId": offering.course_id,
        "courseCode": course_code,
        "title": offering.title,
        "semester": offering.semester,
        "sectionCode": offering.section_code,
        "status": str(offering.state),
        "leadMembershipId": lead_membership_id,
        "version": offering.version,
    }


def _summary_view(row: dict[str, Any]) -> dict[str, Any]:
    return offering_view(offering_from_row(row), row["course_code"], row["lead_membership_id"])


def student_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["user_id"],
        "displayName": row["full_name"],
        "email": row["email"],
        "studentCode": row["student_code"],
    }


def registration_view(
    registration: CourseRegistration, course: Course, student: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "id": registration.registration_id,
        "course": course_view(course),
        "student": student,
        "status": str(registration.status),
        "requestedAt": registration.requested_at,
        "decidedAt": registration.decided_at,
    }


def membership_view(membership: CourseMembership, account: dict[str, Any]) -> dict[str, Any]:
    """Membership response shape (OpenAPI contract)."""
    lead = membership.course_role == CourseRole.PRIMARY_INSTRUCTOR
    return {
        "id": membership.membership_id,
        "offeringId": membership.offering_id,
        "account": account,
        "role": "STUDENT" if membership.course_role == CourseRole.STUDENT else "INSTRUCTOR",
        "teachingRole": "LEAD"
        if lead
        else "CO_INSTRUCTOR"
        if membership.course_role == CourseRole.CO_INSTRUCTOR
        else None,
        "status": str(membership.status),
        "version": membership.version,
    }


def _account_summary(user_id, full_name, status, role, must_change) -> dict[str, Any]:
    return {
        "id": user_id,
        "displayName": full_name,
        "status": str(status),
        "role": str(role),
        "mustChangePassword": bool(must_change),
    }


def _page(items: list, page: int, page_size: int, total: int) -> dict[str, Any]:
    return {
        "items": items,
        "page": page,
        "pageSize": page_size,
        "totalItems": total,
        "totalPages": (total + page_size - 1) // page_size,
    }


# The two search patterns: anything code-like searches codes, otherwise names.
COURSE_CODE_QUERY = re.compile(r"^[A-Za-z]{2,4}[0-9]{1,4}$")  # CS1, CS10, cs1001
COURSE_NAME_QUERY = re.compile(r"^[\w .,&'()+:/-]{2,100}$")  # letters incl. Vietnamese


class CourseService:
    def __init__(self, database=None):
        self.database = database

    # ------------------------------------------------------------ diagram methods
    def create_course(
        self,
        *,
        actor: Actor,
        faculty: str,
        year: int,
        degree: DegreeLevel,
        name: str,
        credits: Decimal,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Admin adds a catalog course; the code (e.g. CS1001) is generated."""
        if actor.role != SystemRole.ADMIN:
            raise forbidden()
        name = name.strip()
        if not name:
            raise ApiError(400, "INVALID_REQUEST", "Course name must not be blank.")
        stem = Course.code_stem(faculty, year, degree)
        with self.database.transaction() as connection:
            sql = Sql(connection)
            repo = CourseRepository(sql)
            number = (repo.max_course_number(stem) or 0) + 1
            if number > Course.MAX_NUMBER:
                raise ApiError(
                    409, "COURSE_CODE_EXHAUSTED", f"All codes {stem}01-{stem}99 are in use."
                )
            course = repo.insert_course(
                course_code=Course.make_code(faculty, year, degree, number),
                course_name=name,
                credits=credits,
                description=(description or "").strip() or None,
            )
            AuditRepository(sql).record(
                actor_id=actor.user_id,
                action="COURSE_CREATED",
                target_type="COURSE",
                target_id=course.course_id,
                details={"courseCode": course.course_code},
            )
        return course_view(course)

    def create_offering(
        self,
        *,
        actor: Actor,
        course_code: str,
        semester: str,
        title: str,
        instructor_email: str | None = None,
        section_code: str,
        learning_information: str = "",
    ) -> dict[str, Any]:
        """Create a draft section with its active lead in one transaction.

        Admin: names the professor by email (an active instructor).
        Instructor with canCreateCourse: becomes the professor; may not name someone else.
        """
        semester, title = semester.strip(), title.strip()
        if not semester or not title:
            raise ApiError(400, "INVALID_REQUEST", "Semester and title must not be blank.")
        try:
            with self.database.transaction() as connection:
                sql = Sql(connection)
                identity = IdentityRepository(sql)
                repo = CourseRepository(sql)
                lead_id = self._offering_lead(identity, actor, instructor_email)
                course = repo.find_course_by_code(course_code.strip().upper())
                if course is None:
                    raise not_found("Course")
                section = section_code.strip()
                if not section:
                    raise ApiError(400, "INVALID_REQUEST", "Section code must not be blank.")
                offering = repo.insert_offering(
                    course_id=course.course_id,
                    semester=semester,
                    section_code=section,
                    title=title,
                    created_by=lead_id,
                )
                repo.insert_membership(
                    offering_id=offering.offering_id,
                    user_id=lead_id,
                    course_role=CourseRole.PRIMARY_INSTRUCTOR,
                )
                AuditRepository(sql).record(
                    actor_id=actor.user_id,
                    action="OFFERING_CREATED",
                    target_type="OFFERING",
                    target_id=offering.offering_id,
                    details={"courseCode": course.course_code, "leadId": lead_id},
                )
                sql.execute(
                    "UPDATE course_offerings SET learning_information=%s WHERE offering_id=%s",
                    learning_information,
                    offering.offering_id,
                )
                return self._workspace_view(sql, actor, repo.offering_summary(offering.offering_id))
        except Exception as error:
            if is_unique_violation(error):
                raise conflict("SECTION_TAKEN", "This course section already exists.") from None
            raise

    @staticmethod
    def _offering_lead(
        identity: IdentityRepository, actor: Actor, instructor_email: str | None
    ) -> int:
        """Who becomes the class's primary instructor, after the permission check."""
        if actor.role == SystemRole.ADMIN:
            if not instructor_email:
                raise ApiError(400, "INVALID_REQUEST", "instructorEmail is required for admins.")
            row = identity.find_by_email(normalize_email(instructor_email))
            user = user_from_row(row) if row else None
            if user is None or not user.has_role(SystemRole.INSTRUCTOR) or not user.is_active():
                raise ApiError(422, "INSTRUCTOR_NOT_FOUND", "No active instructor has this email.")
            return user.user_id
        if actor.role == SystemRole.INSTRUCTOR:
            me = identity.get_account(actor.user_id)
            if not me or not me["can_create_course"]:
                raise forbidden()
            if instructor_email and normalize_email(instructor_email) != me["email"]:
                raise ApiError(400, "INVALID_REQUEST", "Instructors create classes for themselves.")
            return actor.user_id
        raise forbidden()

    def search_courses(
        self, *, actor: Actor, query: str | None, page: int, page_size: int
    ) -> dict[str, Any]:
        """Catalog search for any signed-in user: by code prefix or by name (see patterns)."""
        query = (query or "").strip()
        code_prefix = name_part = None
        if COURSE_CODE_QUERY.match(query):
            code_prefix = query.upper()
        elif COURSE_NAME_QUERY.match(query):
            name_part = query
        elif query:
            raise ApiError(
                400,
                "INVALID_SEARCH",
                "Search by a course code (e.g. CS1001, CS10) or a name of 2-100 characters.",
            )
        with self.database.transaction() as connection:
            courses, total = CourseRepository(Sql(connection)).search_courses(
                code_prefix=code_prefix,
                name_part=name_part,
                offset=(page - 1) * page_size,
                limit=page_size,
            )
        return _page([course_view(course) for course in courses], page, page_size, total)

    def request_enrollment(self, *, actor: Actor, course_id: int) -> dict[str, Any]:
        """A student asks to take a catalog course; an admin reviews the PENDING request."""
        if actor.role != SystemRole.STUDENT:
            raise forbidden()
        try:
            with self.database.transaction() as connection:
                repo = CourseRepository(Sql(connection))
                course = repo.find_course(course_id)
                if course is None:
                    raise not_found("Course")
                registration = repo.insert_registration(
                    course_id=course_id, student_id=actor.user_id
                )
        except Exception as error:
            if is_unique_violation(error):
                raise conflict(
                    "ALREADY_REQUESTED",
                    "You already have a pending or approved request for this course.",
                ) from None
            raise
        return registration_view(registration, course)

    def list_registrations(
        self, *, actor: Actor, status: str | None, page: int, page_size: int
    ) -> dict[str, Any]:
        """Admin review queue (team addition: the admin needs to find the requests)."""
        if actor.role != SystemRole.ADMIN:
            raise forbidden()
        with self.database.transaction() as connection:
            rows, total = CourseRepository(Sql(connection)).list_registrations(
                status=status, offset=(page - 1) * page_size, limit=page_size
            )
        items = [
            registration_view(registration_from_row(r), course_from_row(r), student_view(r))
            for r in rows
        ]
        return _page(items, page, page_size, total)

    def review_registration(
        self, *, actor: Actor, registration_id: int, approve: bool
    ) -> dict[str, Any]:
        """Admin approves or rejects a PENDING request (CourseRegistration.approve/reject)."""
        if actor.role != SystemRole.ADMIN:
            raise forbidden()
        with self.database.transaction() as connection:
            sql = Sql(connection)
            repo = CourseRepository(sql)
            row = repo.get_registration(registration_id)
            if row is None:
                raise not_found("Registration")
            registration = registration_from_row(row)
            if approve:
                registration.approve(actor.user_id)
            else:
                registration.reject(actor.user_id)
            saved = repo.save_decision(registration)
            AuditRepository(sql).record(
                actor_id=actor.user_id,
                action=f"REGISTRATION_{saved.status}",
                target_type="REGISTRATION",
                target_id=registration_id,
                details={"courseId": saved.course_id, "studentId": saved.student_id},
            )
        return registration_view(saved, course_from_row(row), student_view(row))

    def list_approved_students(self, *, actor: Actor, offering_id: int) -> dict[str, Any]:
        """The class professor's waiting list: approved for the course, not in a class yet."""
        with self.database.transaction() as connection:
            repo = CourseRepository(Sql(connection))
            offering = self._require_lead(repo, actor, offering_id, allow_admin=True)
            rows = repo.list_approved_students(offering.course_id)
        return {
            "items": [
                {
                    **student_view(row),
                    "account": _account_summary(
                        row["user_id"],
                        row["full_name"],
                        "ACTIVE",
                        "STUDENT",
                        row["must_change_pwd"],
                    ),
                }
                for row in rows
            ]
        }

    def enroll_student(
        self,
        *,
        actor: Actor,
        offering_id: int,
        student_email: str | None = None,
        account_id: int | None = None,
    ) -> dict[str, Any]:
        """The class lead adds an active existing student by email or account ID."""
        with self.database.transaction() as connection:
            sql = Sql(connection)
            repo = CourseRepository(sql)
            repo.get_offering(offering_id, lock=True)
            offering = self._require_lead(repo, actor, offering_id)
            if not offering.is_open():
                raise conflict("CLASS_NOT_OPEN", "Students can only be added to open classes.")
            row = (
                IdentityRepository(sql).get_account(account_id)
                if account_id
                else IdentityRepository(sql).find_by_email(normalize_email(student_email))
            )
            student = (
                user_from_row(IdentityRepository(sql).get_account(row["user_id"], lock=True))
                if row
                else None
            )
            if not student or not student.has_role(SystemRole.STUDENT) or not student.is_active():
                raise ApiError(422, "STUDENT_NOT_FOUND", "No active student has this email.")
            existing = repo.find_membership(offering_id, student.user_id)
            if existing is not None:
                raise conflict(
                    "ALREADY_ENROLLED" if existing.is_active() else "MEMBERSHIP_REMOVED",
                    "An enrollment record already exists for this class.",
                )
            if repo.is_in_course(course_id=offering.course_id, user_id=student.user_id):
                raise conflict("ALREADY_ENROLLED", "This student is already in a class of it.")
            membership = repo.insert_membership(
                offering_id=offering_id, user_id=student.user_id, course_role=CourseRole.STUDENT
            )
            AuditRepository(sql).record(
                actor_id=actor.user_id,
                action="STUDENT_ENROLLED",
                target_type="OFFERING",
                target_id=offering_id,
                details={"studentId": student.user_id},
            )
        account = _account_summary(
            student.user_id,
            student.full_name,
            student.status,
            student.role,
            student.must_change_password,
        )
        return membership_view(membership, account)

    def list_my_offerings(self, *, actor: Actor, page: int, page_size: int) -> dict[str, Any]:
        """My classes (students and professors); admins see every class."""
        member_id = None if actor.role == SystemRole.ADMIN else actor.user_id
        with self.database.transaction() as connection:
            rows, total = CourseRepository(Sql(connection)).list_offerings(
                member_id=member_id, offset=(page - 1) * page_size, limit=page_size
            )
            return _page(
                [self._workspace_view(Sql(connection), actor, row) for row in rows],
                page,
                page_size,
                total,
            )

    def get_offering(self, *, actor: Actor, offering_id: int) -> dict[str, Any]:
        """Class page header; members and admins only."""
        with self.database.transaction() as connection:
            repo = CourseRepository(Sql(connection))
            self._require_member(repo, actor, offering_id)
            row = repo.offering_summary(offering_id)
            return self._workspace_view(Sql(connection), actor, row)

    def get_roster(
        self, *, actor: Actor, offering_id: int, page: int, page_size: int
    ) -> dict[str, Any]:
        """Active members, professor first; members and admins only."""
        with self.database.transaction() as connection:
            repo = CourseRepository(Sql(connection))
            self._require_member(repo, actor, offering_id)
            rows, total = repo.list_memberships(
                offering_id, offset=(page - 1) * page_size, limit=page_size
            )
        items = [
            membership_view(
                membership_from_row(r),
                _account_summary(
                    r["user_id"],
                    r["full_name"],
                    r["account_status"],
                    r["account_role"],
                    r["must_change_pwd"],
                ),
            )
            for r in rows
        ]
        return _page(items, page, page_size, total)

    # ------------------------------------------------------------ access checks
    @staticmethod
    def _require_member(repo: CourseRepository, actor: Actor, offering_id: int) -> None:
        """Admins, or active members of the class. Others get 404 (class stays private)."""
        offering = repo.get_offering(offering_id)
        if offering is None:
            raise not_found("Class")
        if actor.role == SystemRole.ADMIN:
            return
        membership = repo.find_membership(offering_id, actor.user_id)
        if (
            membership is None
            or not membership.is_active()
            or (offering.state == "DRAFT" and membership.course_role == CourseRole.STUDENT)
        ):
            raise not_found("Class")

    @staticmethod
    def _require_lead(
        repo: CourseRepository, actor: Actor, offering_id: int, *, allow_admin: bool = False
    ) -> CourseOffering:
        """The class's professor (active primary instructor); optionally admins too."""
        offering = repo.get_offering(offering_id)
        if offering is None:
            raise not_found("Class")
        if allow_admin and actor.role == SystemRole.ADMIN:
            return offering
        membership = repo.find_membership(offering_id, actor.user_id)
        if (
            membership is None
            or not membership.is_active()
            or membership.course_role != CourseRole.PRIMARY_INSTRUCTOR
        ):
            raise forbidden()
        return offering

    def add_co_instructor(self, **kwargs: object):
        raise FeatureNotImplemented("CourseService.add_co_instructor")

    def get_course_progress(self, **kwargs: object):
        raise FeatureNotImplemented("CourseService.get_course_progress")

    def get_my_calendar(self, **kwargs: object):
        raise FeatureNotImplemented("CourseService.get_my_calendar")

    def get_my_progress(self, **kwargs: object):
        raise FeatureNotImplemented("CourseService.get_my_progress")

    def mark_resource_complete(self, **kwargs: object):
        raise FeatureNotImplemented("CourseService.mark_resource_complete")

    def remove_instructor_membership(self, **kwargs: object):
        raise FeatureNotImplemented("CourseService.remove_instructor_membership")

    def transfer_leadership(self, **kwargs: object):
        raise FeatureNotImplemented("CourseService.transfer_leadership")

    def unmark_resource_complete(self, **kwargs: object):
        raise FeatureNotImplemented("CourseService.unmark_resource_complete")

    def publish_offering(self, **kwargs: object):
        raise FeatureNotImplemented("CourseService.publish_offering")

    def archive_offering(self, **kwargs: object):
        raise FeatureNotImplemented("CourseService.archive_offering")

    def transfer_lead(self, **kwargs: object):
        raise FeatureNotImplemented("CourseService.transfer_lead")

    def _workspace_view(self, sql, actor, row):
        repo = CourseRepository(sql)
        view = _summary_view(row)
        metadata = repo.metadata(view["id"])
        membership = repo.find_membership(view["id"], actor.user_id)
        lead = (
            membership is not None
            and membership.is_active()
            and membership.course_role == CourseRole.PRIMARY_INSTRUCTOR
        )
        teacher = (
            membership is not None
            and membership.is_active()
            and membership.course_role in (CourseRole.PRIMARY_INSTRUCTOR, CourseRole.CO_INSTRUCTOR)
        )
        admin = actor.role == SystemRole.ADMIN
        writable = view["status"] != "ARCHIVED"
        lead_account = sql.one(
            """SELECT u.user_id, u.full_name, u.status, u.role, u.must_change_pwd
            FROM course_memberships AS m JOIN users AS u ON u.user_id=m.user_id
            WHERE m.membership_id=%s""",
            view["leadMembershipId"],
        )
        view.update(
            {
                "permissions": {
                    "academic": bool(membership and membership.is_active()),
                    "teach": teacher and writable,
                    "edit": lead and writable,
                    "publish": lead and view["status"] == "DRAFT",
                    "archive": lead and view["status"] == "OPEN",
                    "restore": (lead or admin) and not writable,
                    "manageTeam": False,
                    "repairLead": False,
                    "enroll": lead and view["status"] == "OPEN",
                    "manageCode": lead and writable,
                },
                "lead": _account_summary(
                    lead_account["user_id"],
                    lead_account["full_name"],
                    lead_account["status"],
                    lead_account["role"],
                    lead_account["must_change_pwd"],
                )
                if lead_account
                else None,
                "teachingRole": "LEAD" if lead else "CO_INSTRUCTOR" if teacher else None,
                "learningInformation": metadata["learning_information"]
                if membership and membership.is_active()
                else None,
                "joinCode": metadata["join_code"] if lead else None,
                "joinEnabled": bool(metadata["join_code_enabled"]) if lead else False,
                "completedMaterials": 0,
                "totalMaterials": 0,
            }
        )
        if membership and membership.is_active():
            view["totalMaterials"] = sql.scalar(
                "SELECT COUNT(*) FROM materials AS m JOIN topics AS t ON t.topic_id=m.topic_id WHERE t.offering_id=%s AND m.status='PUBLISHED'",
                view["id"],
            )
            view["completedMaterials"] = (
                sql.scalar(
                    "SELECT COUNT(*) FROM material_completions AS c JOIN materials AS m ON m.material_id=c.material_id JOIN topics AS t ON t.topic_id=m.topic_id WHERE t.offering_id=%s AND m.status='PUBLISHED' AND c.student_id=%s",
                    view["id"],
                    actor.user_id,
                )
                if actor.role == SystemRole.STUDENT
                else 0
            )
        return view

    def update_course(self, *, actor, offering_id, expected_version, changes):
        try:
            with self.database.transaction() as connection:
                sql = Sql(connection)
                repo = CourseRepository(sql)
                repo.get_offering(offering_id, lock=True)
                offering = self._require_lead(repo, actor, offering_id, allow_admin=True)
                if offering.version != expected_version:
                    raise version_conflict(offering.version)
                old = self._workspace_view(sql, actor, repo.offering_summary(offering_id))
                target = changes.get("status", old["status"])
                if actor.role == SystemRole.ADMIN and (
                    target != "OPEN"
                    or old["status"] != "ARCHIVED"
                    or not changes.get("reason", "").strip()
                    or set(changes) - {"status", "reason"}
                ):
                    raise forbidden(
                        "Administrators may restore metadata with a reason; academic edits require teaching access."
                    )
                if old["status"] == "ARCHIVED" and (
                    target != "OPEN" or set(changes) - {"status", "reason"}
                ):
                    raise conflict("CLASS_READ_ONLY", "Restore the class before making changes.")
                allowed = {
                    "DRAFT": {"DRAFT", "OPEN"},
                    "OPEN": {"OPEN", "ARCHIVED"},
                    "ARCHIVED": {"OPEN"},
                }
                if target not in allowed[old["status"]]:
                    raise conflict("INVALID_TRANSITION", "Invalid class state transition.")
                if target in ("DRAFT", "OPEN") and (
                    old["lead"] is None or old["lead"]["status"] != "ACTIVE"
                ):
                    raise conflict("ACTIVE_LEAD_REQUIRED", "An active lead instructor is required.")
                if target == "ARCHIVED" and repo.has_unfinished_attempts(offering_id):
                    raise conflict("ATTEMPTS_PENDING", "Finalize quiz attempts before archiving.")
                data = {
                    k: old[k]
                    for k in [
                        "title",
                        "semester",
                        "sectionCode",
                        "learningInformation",
                        "status",
                        "joinCode",
                        "joinEnabled",
                    ]
                }
                metadata = repo.metadata(offering_id)
                data.update(
                    learningInformation=metadata["learning_information"],
                    joinCode=metadata["join_code"],
                    joinEnabled=bool(metadata["join_code_enabled"]),
                )
                for k in ["title", "semester", "sectionCode", "learningInformation", "status"]:
                    if k in changes:
                        data[k] = changes[k]
                if any(not data[k].strip() for k in ["title", "semester", "sectionCode"]):
                    raise ApiError(400, "INVALID_REQUEST", "Class fields must not be blank.")
                if changes.get("joinCodeAction") == "rotate":
                    data["joinCode"] = "".join(
                        secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6)
                    )
                    data["joinEnabled"] = True
                elif changes.get("joinCodeAction") == "disable":
                    data["joinEnabled"] = False
                repo.update_offering(offering_id, data)
                AuditRepository(sql).record(
                    actor_id=actor.user_id,
                    action="OFFERING_UPDATED",
                    target_type="OFFERING",
                    target_id=offering_id,
                    details={"status": target, "reason": changes.get("reason")},
                )
                return self._workspace_view(sql, actor, repo.offering_summary(offering_id))
        except Exception as error:
            if is_unique_violation(error):
                raise conflict(
                    "SECTION_OR_CODE_TAKEN",
                    "Section or join code is already in use; choose another section or retry code generation.",
                ) from None
            raise

    def restore_offering(self, *, actor, offering_id, expected_version, reason):
        return self.update_course(
            actor=actor,
            offering_id=offering_id,
            expected_version=expected_version,
            changes={"status": "OPEN", "reason": reason},
        )

    def get_teaching_team(self, *, actor, offering_id, page=1, page_size=25):
        with self.database.transaction() as connection:
            sql = Sql(connection)
            repo = CourseRepository(sql)
            self._require_member(repo, actor, offering_id)
            where = "m.offering_id=%s AND m.status='ACTIVE' AND m.course_role <> 'STUDENT'"
            total = sql.scalar(
                f"SELECT COUNT(*) FROM course_memberships AS m WHERE {where}", offering_id
            )
            rows = sql.all(
                f"SELECT m.*,u.full_name,u.status AS account_status,u.role AS account_role,u.must_change_pwd FROM course_memberships AS m JOIN users AS u ON u.user_id=m.user_id WHERE {where} ORDER BY m.membership_id LIMIT %s, %s",
                offering_id,
                (page - 1) * page_size,
                page_size,
            )
            return _page(
                [
                    membership_view(
                        membership_from_row(r),
                        _account_summary(
                            r["user_id"],
                            r["full_name"],
                            r["account_status"],
                            r["account_role"],
                            r["must_change_pwd"],
                        ),
                    )
                    for r in rows
                ],
                page,
                page_size,
                total,
            )

    def join_by_code(self, *, actor, code, offering_id=None):
        if actor.role != SystemRole.STUDENT:
            raise forbidden()
        with self.database.transaction() as connection:
            sql = Sql(connection)
            repo = CourseRepository(sql)
            target = repo.resolve_join_code(code.upper())
            if target is None or (offering_id is not None and target != offering_id):
                raise not_found("Join code")
            IdentityRepository(sql).get_account(actor.user_id, lock=True)
            existing = repo.find_membership(target, actor.user_id)
            if existing and existing.is_active():
                account = IdentityRepository(sql).get_account(actor.user_id)
                return membership_view(
                    existing,
                    _account_summary(
                        account["user_id"],
                        account["full_name"],
                        account["status"],
                        account["role"],
                        account["must_change_pwd"],
                    ),
                )
            if existing:
                raise conflict(
                    "MEMBERSHIP_REMOVED", "Ask your instructor to restore your membership."
                )
            offering = repo.get_offering(target)
            if repo.is_in_course(course_id=offering.course_id, user_id=actor.user_id):
                raise conflict("ALREADY_ENROLLED", "You already belong to a class of this course.")
            member = repo.insert_membership(
                offering_id=target, user_id=actor.user_id, course_role=CourseRole.STUDENT
            )
            account = IdentityRepository(sql).get_account(actor.user_id)
            AuditRepository(sql).record(
                actor_id=actor.user_id,
                action="STUDENT_JOINED",
                target_type="OFFERING",
                target_id=target,
                details={},
            )
            return membership_view(
                member,
                _account_summary(
                    account["user_id"],
                    account["full_name"],
                    account["status"],
                    account["role"],
                    account["must_change_pwd"],
                ),
            )

    def get_catalog_course(self, *, actor, course_id):
        with self.database.read_connection() as connection:
            course = CourseRepository(Sql(connection)).find_course(course_id)
            if course is None:
                raise not_found("Course")
            return course_view(course)

    def get_dashboard(self, *, actor):
        with self.database.transaction() as connection:
            sql = Sql(connection)
            now = sql.scalar("SELECT UTC_TIMESTAMP(6)")
            if actor.role == SystemRole.ADMIN:
                counts = {
                    "accounts": sql.scalar("SELECT COUNT(*) FROM users"),
                    "lockedAccounts": sql.scalar(
                        "SELECT COUNT(*) FROM users WHERE status='LOCKED'"
                    ),
                    "openSections": sql.scalar(
                        "SELECT COUNT(*) FROM course_offerings WHERE state='OPEN'"
                    ),
                }
                return {
                    "serverNow": now,
                    "role": str(actor.role),
                    "counts": counts,
                    "sections": [],
                    "assignments": [],
                }
            rows = sql.all(
                f"""{_OFFERING_SUMMARY_SELECT}
                WHERE EXISTS (SELECT 1 FROM course_memberships AS me WHERE me.offering_id=o.offering_id AND me.user_id=%s AND me.status='ACTIVE')
                AND (o.state <> 'DRAFT' OR EXISTS (SELECT 1 FROM course_memberships AS me WHERE me.offering_id=o.offering_id AND me.user_id=%s AND me.course_role <> 'STUDENT' AND me.status='ACTIVE'))
                ORDER BY o.semester DESC,o.offering_id""",
                actor.user_id,
                actor.user_id,
            )
            sections = [_summary_view(r) for r in rows]
            assignments = sql.all(
                """SELECT a.activity_id AS id,a.offering_id AS offeringId,a.title,
                    x.due_at AS dueAt,x.cutoff_at AS cutoffAt,
                    CASE WHEN EXISTS (SELECT 1 FROM submissions AS s WHERE s.assignment_id=a.activity_id AND s.student_id=%s AND s.status='SUBMITTED') THEN 1 ELSE 0 END AS submitted
                FROM activities AS a JOIN assignments AS x ON x.activity_id=a.activity_id
                JOIN course_offerings AS o ON o.offering_id=a.offering_id
                JOIN course_memberships AS me ON me.offering_id=o.offering_id AND me.user_id=%s AND me.status='ACTIVE'
                WHERE o.state='OPEN' AND a.status='PUBLISHED'
                ORDER BY x.due_at,a.activity_id""",
                actor.user_id,
                actor.user_id,
            )
            return {
                "serverNow": now,
                "role": str(actor.role),
                "counts": {
                    "openSections": sum(o["status"] == "OPEN" for o in sections),
                    "missingSubmissions": sum(
                        not a["submitted"] and a["cutoffAt"] >= now for a in assignments
                    )
                    if actor.role == SystemRole.STUDENT
                    else None,
                },
                "sections": sections,
                "assignments": assignments,
            }

    def enrollment_candidates(self, *, actor, offering_id, page=1, page_size=25, search=None):
        with self.database.transaction() as connection:
            sql = Sql(connection)
            repo = CourseRepository(sql)
            offering = self._require_lead(repo, actor, offering_id)
            if not offering.is_open():
                raise conflict("CLASS_NOT_OPEN", "Enrollment requires an open class.")
            rows, total = repo.enrollment_candidates(
                offering.course_id, offering_id, search, (page - 1) * page_size, page_size
            )
            return _page(
                [
                    _account_summary(
                        r["user_id"], r["full_name"], r["status"], r["role"], r["must_change_pwd"]
                    )
                    for r in rows
                ],
                page,
                page_size,
                total,
            )
