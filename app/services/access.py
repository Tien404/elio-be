"""Class access checks shared by ContentService and SubmissionService.

Classes are private: anyone who is not an active member (admins included) gets 404, so
they cannot even tell the class exists. Members without the needed role get 403.
"""

from app.core.errors import forbidden, not_found
from app.domain.context import Actor
from app.domain.entities import CourseMembership, CourseRole
from app.infrastructure.db.repositories.course_repository import CourseRepository


def require_member(repo: CourseRepository, actor: Actor, offering_id: int) -> CourseMembership:
    if repo.get_offering(offering_id) is None:
        raise not_found("Class")
    membership = repo.find_membership(offering_id, actor.user_id)
    if membership is None or not membership.is_active():
        raise not_found("Class")
    return membership


def require_teacher(repo: CourseRepository, actor: Actor, offering_id: int) -> CourseMembership:
    membership = require_member(repo, actor, offering_id)
    if not is_teacher(membership):
        raise forbidden()
    return membership


def require_student(repo: CourseRepository, actor: Actor, offering_id: int) -> CourseMembership:
    membership = require_member(repo, actor, offering_id)
    if membership.course_role != CourseRole.STUDENT:
        raise forbidden()
    return membership


def is_teacher(membership: CourseMembership) -> bool:
    return membership.course_role == CourseRole.PRIMARY_INSTRUCTOR
