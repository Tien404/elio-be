from app.core.errors import conflict, forbidden, not_found
from app.domain.context import Actor
from app.domain.entities import CourseRole, CourseState
from app.infrastructure.db.repositories.course_repository import CourseRepository


def require_member(repo: CourseRepository, actor: Actor, offering_id: int):
    offering = repo.get_offering(offering_id)
    if offering is None:
        raise not_found("Class")
    membership = repo.find_membership(offering_id, actor.user_id)
    if membership is None or not membership.is_active():
        raise not_found("Class")
    if offering.state == CourseState.DRAFT and not is_teacher(membership):
        raise not_found("Class")
    return membership


def require_writable(repo: CourseRepository, offering_id: int, *, open_only=False):
    offering = repo.get_offering(offering_id, lock=True)
    if offering is None:
        raise not_found("Class")
    if offering.state == CourseState.ARCHIVED or (open_only and not offering.is_open()):
        raise conflict("CLASS_READ_ONLY", "This class does not accept changes.")
    return offering


def require_teacher(repo: CourseRepository, actor: Actor, offering_id: int):
    membership = require_member(repo, actor, offering_id)
    if not is_teacher(membership):
        raise forbidden()
    require_writable(repo, offering_id)
    return membership


def require_student(repo: CourseRepository, actor: Actor, offering_id: int):
    membership = require_member(repo, actor, offering_id)
    if membership.course_role != CourseRole.STUDENT:
        raise forbidden()
    require_writable(repo, offering_id, open_only=True)
    return membership


def is_teacher(membership) -> bool:
    return membership.course_role in (CourseRole.PRIMARY_INSTRUCTOR, CourseRole.CO_INSTRUCTOR)
