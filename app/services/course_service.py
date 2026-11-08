"""CourseService from the class diagram: catalog courses, classes (offerings), enrollment.

Methods still raising FeatureNotImplemented back the 501 placeholder routes; they are
replaced one by one as the MVP steps are built.
"""

import re
from decimal import Decimal
from typing import Any

from app.core.errors import ApiError, FeatureNotImplemented, conflict, forbidden, not_found
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
        "teachingRole": "LEAD" if lead else None,
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
    ) -> dict[str, Any]:
        """Create a class of a catalog course; it opens at once with a generated section.

        Admin: names the professor by email (an active instructor).
        Instructor with canCreateCourse: becomes the professor; may not name someone else.
        """
        semester, title = semester.strip(), title.strip()
        if not semester or not title:
            raise ApiError(400, "INVALID_REQUEST", "Semester and title must not be blank.")
        with self.database.transaction() as connection:
            sql = Sql(connection)
            identity = IdentityRepository(sql)
            repo = CourseRepository(sql)
            lead_id = self._offering_lead(identity, actor, instructor_email)
            course = repo.find_course_by_code(course_code.strip().upper())
            if course is None:
                raise not_found("Course")
            section = (repo.max_section_number(course.course_id, semester) or 0) + 1
            offering = repo.insert_offering(
                course_id=course.course_id,
                semester=semester,
                section_code=f"{section:02d}",
                title=title,
                created_by=lead_id,
            )
            lead = repo.insert_membership(
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
        return offering_view(offering, course.course_code, lead.membership_id)

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
        return {"items": [student_view(row) for row in rows]}

    def enroll_student(
        self, *, actor: Actor, offering_id: int, student_email: str
    ) -> dict[str, Any]:
        """The class professor adds an approved student by email."""
        with self.database.transaction() as connection:
            sql = Sql(connection)
            repo = CourseRepository(sql)
            offering = self._require_lead(repo, actor, offering_id)
            if not offering.is_open():
                raise conflict("CLASS_NOT_OPEN", "Students can only be added to open classes.")
            row = IdentityRepository(sql).find_by_email(normalize_email(student_email))
            student = user_from_row(row) if row else None
            if not student or not student.has_role(SystemRole.STUDENT) or not student.is_active():
                raise ApiError(422, "STUDENT_NOT_FOUND", "No active student has this email.")
            if not repo.lock_approved_registration(
                course_id=offering.course_id, student_id=student.user_id
            ):
                raise conflict(
                    "NOT_APPROVED", "This student has no approved request for this course."
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
        return _page([_summary_view(row) for row in rows], page, page_size, total)

    def get_offering(self, *, actor: Actor, offering_id: int) -> dict[str, Any]:
        """Class page header; members and admins only."""
        with self.database.transaction() as connection:
            repo = CourseRepository(Sql(connection))
            self._require_member(repo, actor, offering_id)
            row = repo.offering_summary(offering_id)
        return _summary_view(row)

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
        if repo.get_offering(offering_id) is None:
            raise not_found("Class")
        if actor.role == SystemRole.ADMIN:
            return
        membership = repo.find_membership(offering_id, actor.user_id)
        if membership is None or not membership.is_active():
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

    # ------------------------------------------- placeholders behind 501 routes
    def add_co_instructor(self, **kwargs: object):
        raise FeatureNotImplemented("CourseService.add_co_instructor")

    def get_course_progress(self, **kwargs: object):
        raise FeatureNotImplemented("CourseService.get_course_progress")

    def get_dashboard(self, **kwargs: object):
        raise FeatureNotImplemented("CourseService.get_dashboard")

    def get_my_calendar(self, **kwargs: object):
        raise FeatureNotImplemented("CourseService.get_my_calendar")

    def get_my_progress(self, **kwargs: object):
        raise FeatureNotImplemented("CourseService.get_my_progress")

    def get_teaching_team(self, **kwargs: object):
        raise FeatureNotImplemented("CourseService.get_teaching_team")

    def mark_resource_complete(self, **kwargs: object):
        raise FeatureNotImplemented("CourseService.mark_resource_complete")

    def remove_instructor_membership(self, **kwargs: object):
        raise FeatureNotImplemented("CourseService.remove_instructor_membership")

    def restore_offering(self, **kwargs: object):
        raise FeatureNotImplemented("CourseService.restore_offering")

    def transfer_leadership(self, **kwargs: object):
        raise FeatureNotImplemented("CourseService.transfer_leadership")

    def unmark_resource_complete(self, **kwargs: object):
        raise FeatureNotImplemented("CourseService.unmark_resource_complete")

    def update_course(self, **kwargs: object):
        raise FeatureNotImplemented("CourseService.update_course")

    def publish_offering(self, **kwargs: object):
        raise FeatureNotImplemented("CourseService.publish_offering")

    def archive_offering(self, **kwargs: object):
        raise FeatureNotImplemented("CourseService.archive_offering")

    def transfer_lead(self, **kwargs: object):
        raise FeatureNotImplemented("CourseService.transfer_lead")
