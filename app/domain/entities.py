import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
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
class AssignmentGroup:
    """Students who hand in one submission together. Members are locked once the group
    has submitted (or been graded)."""

    group_id: int
    assignment_id: int
    name: str
    member_ids: list[int] = field(default_factory=list)
    locked: bool = False

    def join(self, student_id: int, max_size: int) -> None:
        self._check_open()
        if student_id in self.member_ids:
            raise ValueError("You are already in this group.")
        if len(self.member_ids) >= max_size:
            raise ValueError(f"This group is full ({max_size} members).")
        self.member_ids.append(student_id)

    def leave(self, student_id: int) -> None:
        self._check_open()
        if student_id not in self.member_ids:
            raise ValueError("You are not in this group.")
        self.member_ids.remove(student_id)

    def _check_open(self) -> None:
        if self.locked:
            raise ValueError("This group has already submitted; its members are fixed.")


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


class SpecialMark(StrEnum):
    """School special grades; both count as 0."""

    ABSENT = "ABSENT"  # code 11: absent from the test
    BANNED = "BANNED"  # code 12: banned from the exam

    @property
    def code(self) -> int:
        return 11 if self == SpecialMark.ABSENT else 12


@dataclass
class Grade:
    """The professor's grade for one submission (a draft until the assignment's grades
    are released). Every save is kept as a revision."""

    grade_id: int
    submission_id: int
    score: Decimal
    status: PublishStatus
    feedback: str | None = None
    published_at: datetime | None = None
    special_mark: SpecialMark | None = None

    @staticmethod
    def check(
        *,
        score: Decimal | None,
        special_mark: SpecialMark | None,
        max_score: Decimal,
        submitted: bool,
    ) -> Decimal:
        """Validate one grade box; returns the score to store (special marks store 0)."""
        if (score is None) == (special_mark is None):
            raise ValueError("Enter either a score or a special mark (11 or 12).")
        if special_mark is not None:
            if special_mark == SpecialMark.ABSENT and submitted:
                raise ValueError("A student who submitted work cannot be marked absent (11).")
            return Decimal(0)
        if not submitted and score != 0:
            raise ValueError("Missing work can only receive zero or a special mark.")
        if not Decimal(0) <= score <= max_score:
            raise ValueError(f"The score must be between 0 and {max_score}.")
        return score

    def publish(self) -> None:
        self.status = PublishStatus.PUBLISHED  # published_at is set by the database clock


# ======================================================= quizzes (automatic grading)

CENT = Decimal("0.01")


class QuestionType(StrEnum):
    SINGLE_CHOICE = "SINGLE_CHOICE"
    TRUE_FALSE = "TRUE_FALSE"  # options: 1 = True, 2 = False


class GradingMethod(StrEnum):
    """Which attempt counts on the grade page."""

    LATEST_ATTEMPT = "LATEST_ATTEMPT"
    HIGHEST_SCORE = "HIGHEST_SCORE"
    AVERAGE = "AVERAGE"


@dataclass
class Quiz:
    quiz_id: int
    title: str
    open_at: datetime
    close_at: datetime
    duration_minutes: int
    max_score: Decimal  # the quiz total used for grading
    status: PublishStatus
    set_total: Decimal  # the total the professor typed; questions share it
    max_attempts: int = 1  # 0 = unlimited
    grading_method: GradingMethod = GradingMethod.HIGHEST_SCORE

    def is_open(self, at: datetime) -> bool:
        return self.status == PublishStatus.PUBLISHED and self.open_at <= at < self.close_at

    def publish(self) -> None:
        if self.status != PublishStatus.DRAFT:
            raise ValueError("The quiz is already published.")
        self.status = PublishStatus.PUBLISHED

    def distribute_points(self, custom_points: list[Decimal | None]) -> list[Decimal]:
        """Points per question, in order. None = equal share of what the hand-set (custom)
        questions leave of set_total. Leftover cents go to the last shared question.
        When every question is custom, max_score becomes their sum."""
        shared = [i for i, value in enumerate(custom_points) if value is None]
        custom_sum = sum((v for v in custom_points if v is not None), Decimal(0))
        if not shared:
            self.max_score = custom_sum if custom_points else self.set_total
            return list(custom_points)
        remaining = self.set_total - custom_sum
        share = (remaining / len(shared)).quantize(CENT, rounding=ROUND_DOWN)
        if share <= 0:
            raise ValueError(
                f"Hand-set points ({custom_sum}) leave nothing of the quiz total "
                f"({self.set_total}) for the other questions."
            )
        points = list(custom_points)
        for i in shared:
            points[i] = share
        points[shared[-1]] = remaining - share * (len(shared) - 1)
        self.max_score = self.set_total
        return points

    def counted_score(self, scores: list[Decimal]) -> Decimal | None:
        """The score for the grade page, from finished attempts in order (None = no attempt)."""
        if not scores:
            return None
        if self.grading_method == GradingMethod.HIGHEST_SCORE:
            return max(scores)
        if self.grading_method == GradingMethod.LATEST_ATTEMPT:
            return scores[-1]
        return (sum(scores) / len(scores)).quantize(CENT, rounding=ROUND_HALF_UP)

    def can_start(self, attempts_used: int) -> bool:
        return self.max_attempts == 0 or attempts_used < self.max_attempts


@dataclass
class Question:
    question_id: int
    text: str
    type: QuestionType
    options: list[str]  # option numbers are 1, 2, ...
    correct_option: int
    points: Decimal

    def check_answer(self, option: int | None) -> bool:
        return option == self.correct_option


@dataclass
class QuizAttempt:
    attempt_id: int
    started_at: datetime
    ends_at: datetime
    answers: dict[int, int] = field(default_factory=dict)  # question id -> chosen option
    submitted_at: datetime | None = None
    score: Decimal | None = None

    def save_answer(self, question_id: int, option: int) -> None:
        if self.submitted_at is not None:
            raise ValueError("This attempt has already been submitted.")
        self.answers[question_id] = option

    def has_expired(self, at: datetime) -> bool:
        return at >= self.ends_at

    def finish(self, at: datetime) -> None:
        if self.submitted_at is not None:
            raise ValueError("This attempt has already been submitted.")
        self.submitted_at = at

    def grade(self, questions: list[Question]) -> Decimal:
        """Score = sum of points of correctly answered questions."""
        self.score = sum(
            (q.points for q in questions if q.check_answer(self.answers.get(q.question_id))),
            Decimal(0),
        )
        return self.score
