import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from app.core.errors import conflict

# =========================================================== page 1: accounts & courses


class SystemRole(StrEnum):
    STUDENT = "STUDENT"
    INSTRUCTOR = "INSTRUCTOR"
    ADMIN = "ADMIN"


class AccountStatus(StrEnum):
    ACTIVE = "ACTIVE"
    LOCKED = "LOCKED"


class DegreeLevel(StrEnum):
    UNDERGRADUATE = "UNDERGRADUATE"
    MASTERS = "MASTERS"
    PHD = "PHD"


class RegistrationStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class CourseState(StrEnum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    ARCHIVED = "ARCHIVED"


class CourseRole(StrEnum):
    STUDENT = "STUDENT"
    PRIMARY_INSTRUCTOR = "PRIMARY_INSTRUCTOR"
    CO_INSTRUCTOR = "CO_INSTRUCTOR"


class MembershipStatus(StrEnum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


@dataclass
class User:
    user_id: int
    email: str
    full_name: str
    password_hash: str
    role: SystemRole
    status: AccountStatus
    must_change_password: bool

    def has_role(self, role: SystemRole) -> bool:
        return self.role == role

    def is_active(self) -> bool:
        return self.status == AccountStatus.ACTIVE


@dataclass
class Student(User):
    student_code: str


@dataclass
class Instructor(User):
    can_create_course: bool


@dataclass
class Admin(User):
    pass


_FACULTY = re.compile(r"^[A-Z]{2,4}$")
_DEGREE_DIGIT = {
    DegreeLevel.UNDERGRADUATE: 0,
    DegreeLevel.MASTERS: 1,
    DegreeLevel.PHD: 2,
}


@dataclass
class Course:
    course_id: int
    course_code: str
    course_name: str
    credits: Decimal
    description: str | None = None

    MAX_NUMBER = 99

    @staticmethod
    def code_stem(faculty: str, year: int, degree: DegreeLevel) -> str:
        """Code without the course number: CS + 1 + 0 -> 'CS10'."""
        faculty = faculty.upper()
        if not _FACULTY.match(faculty):
            raise ValueError("faculty must be 2-4 letters")
        if not 1 <= year <= 9:
            raise ValueError("year must be 1-9")
        return f"{faculty}{year}{_DEGREE_DIGIT[DegreeLevel(degree)]}"

    @staticmethod
    def make_code(faculty: str, year: int, degree: DegreeLevel, number: int) -> str:
        """CS, 1, UNDERGRADUATE, 1 -> 'CS1001'."""
        if not 1 <= number <= Course.MAX_NUMBER:
            raise ValueError("course number must be 1-99")
        return f"{Course.code_stem(faculty, year, degree)}{number:02d}"


@dataclass
class CourseRegistration:
    registration_id: int
    course_id: int
    student_id: int
    status: RegistrationStatus
    requested_at: datetime
    decided_by: int | None = None
    decided_at: datetime | None = None

    def approve(self, admin_id: int) -> None:
        self._decide(admin_id, RegistrationStatus.APPROVED)

    def reject(self, admin_id: int) -> None:
        self._decide(admin_id, RegistrationStatus.REJECTED)

    def _decide(self, admin_id: int, status: RegistrationStatus) -> None:
        if self.status != RegistrationStatus.PENDING:
            raise conflict("REGISTRATION_ALREADY_DECIDED", "This request was already decided.")
        self.status = status
        self.decided_by = admin_id  # decided_at is set by the database clock


@dataclass
class CourseOffering:
    offering_id: int
    course_id: int
    semester: str
    section_code: str
    title: str
    state: CourseState
    version: int = 1

    def is_open(self) -> bool:
        return self.state == CourseState.OPEN


@dataclass
class CourseMembership:
    membership_id: int
    offering_id: int
    user_id: int
    course_role: CourseRole
    status: MembershipStatus
    joined_at: datetime
    version: int = 1

    def is_active(self) -> bool:
        return self.status == MembershipStatus.ACTIVE


# ============================================= page 2: materials, submissions & grading


class MaterialKind(StrEnum):
    TEXT = "TEXT"
    FILE = "FILE"
    LINK = "LINK"


class PublishStatus(StrEnum):
    ARCHIVED = "ARCHIVED"
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


@dataclass
class Topic:
    topic_id: int
    offering_id: int
    title: str
    position: int
    version: int = 1


@dataclass
class FileAsset:
    """Metadata of a stored file; the bytes live in FileStorage under storage_key."""

    file_id: int
    file_name: str
    mime_type: str
    size_bytes: int
    sha256: str
    storage_key: str


@dataclass
class Material:
    material_id: int
    topic_id: int
    title: str
    kind: MaterialKind
    status: PublishStatus
    url: str | None = None  # LINK
    file: FileAsset | None = None  # FILE
    version: int = 1

    def publish(self) -> None:
        self.status = PublishStatus.PUBLISHED


@dataclass
class Assignment:
    """A submission box; the instructions are posted as a Material."""

    assignment_id: int
    offering_id: int
    topic_id: int
    title: str
    due_at: datetime
    max_score: Decimal
    status: PublishStatus
    instructions: str | None = None
    version: int = 1

    open_at: datetime | None = None
    cutoff_at: datetime | None = None

    def is_open(self, at: datetime | None = None) -> bool:
        if self.status != PublishStatus.PUBLISHED:
            return False
        if at is None:
            return False
        return (
            self.open_at is not None
            and self.cutoff_at is not None
            and self.open_at <= at <= self.cutoff_at
        )

    def is_late(self, at: datetime) -> bool:
        return at > self.due_at

    def publish(self) -> None:
        self.status = PublishStatus.PUBLISHED


@dataclass
class Submission:
    submission_id: int
    assignment_id: int
    student_id: int
    version: int
    submitted_at: datetime
    late: bool
    files: list[FileAsset] = field(default_factory=list)

    MAX_FILES = 5


@dataclass
class Grade:
    grade_id: int
    submission_id: int
    score: Decimal
    status: PublishStatus
    feedback: str | None = None
    published_at: datetime | None = None

    def publish(self) -> None:
        self.status = PublishStatus.PUBLISHED  # published_at is set by the database clock
