"""Rules on the class-diagram entities (no database)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.errors import ApiError
from app.domain.entities import (
    AccountStatus,
    Assignment,
    Course,
    CourseRegistration,
    DegreeLevel,
    PublishStatus,
    RegistrationStatus,
    Student,
    SystemRole,
)

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


def test_course_make_code():
    assert Course.make_code("cs", 1, DegreeLevel.UNDERGRADUATE, 1) == "CS1001"
    assert Course.make_code("MATH", 3, DegreeLevel.MASTERS, 12) == "MATH3112"
    assert Course.make_code("CS", 9, DegreeLevel.PHD, 99) == "CS9299"
    for bad in (("C", 1, 1), ("CSABC", 1, 1), ("C1", 1, 1), ("CS", 0, 1), ("CS", 1, 100)):
        faculty, year, number = bad
        with pytest.raises(ValueError):
            Course.make_code(faculty, year, DegreeLevel.UNDERGRADUATE, number)


def test_user_roles_and_status():
    student = Student(
        user_id=1,
        email="s@elio.test",
        full_name="S",
        password_hash="x",
        role=SystemRole.STUDENT,
        status=AccountStatus.ACTIVE,
        must_change_password=False,
        student_code="S000001",
    )
    assert student.has_role(SystemRole.STUDENT) and not student.has_role(SystemRole.ADMIN)
    assert student.is_active()
    student.status = AccountStatus.LOCKED
    assert not student.is_active()


def test_registration_can_be_decided_once():
    request = CourseRegistration(
        registration_id=1,
        course_id=1,
        student_id=2,
        status=RegistrationStatus.PENDING,
        requested_at=NOW,
    )
    request.approve(admin_id=9)
    assert request.status == RegistrationStatus.APPROVED and request.decided_by == 9
    with pytest.raises(ApiError) as error:
        request.reject(admin_id=9)
    assert error.value.code == "REGISTRATION_ALREADY_DECIDED"


def test_assignment_open_and_late():
    assignment = Assignment(
        assignment_id=1,
        offering_id=1,
        topic_id=1,
        title="HW1",
        due_at=NOW + timedelta(days=7),
        max_score=Decimal("10"),
        status=PublishStatus.DRAFT,
    )
    assert not assignment.is_open()  # drafts accept no submissions
    assignment.publish()
    assert assignment.is_open()
    assert not assignment.is_late(NOW + timedelta(days=7))
    assert assignment.is_late(NOW + timedelta(days=7, seconds=1))
