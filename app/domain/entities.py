from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum

from app.core.errors import FeatureNotImplemented


class SystemRole(str, Enum):
    STUDENT = "STUDENT"
    INSTRUCTOR = "INSTRUCTOR"
    ADMIN = "ADMIN"


@dataclass
class User:
    user_id: int
    full_name: str
    email: str
    role: SystemRole
    status: str
    must_change_password: bool

    def is_active(self, **kwargs: object):
        raise FeatureNotImplemented("User.is_active")

    def lock(self, **kwargs: object):
        raise FeatureNotImplemented("User.lock")

    def unlock(self, **kwargs: object):
        raise FeatureNotImplemented("User.unlock")


@dataclass
class Course:
    course_id: int
    course_code: str
    course_name: str
    credits: Decimal

    def update_details(self, **kwargs: object):
        raise FeatureNotImplemented("Course.update_details")


@dataclass
class CourseOffering:
    offering_id: int
    course_id: int
    semester: str
    section_code: str
    state: str
    version: int

    def publish(self, **kwargs: object):
        raise FeatureNotImplemented("CourseOffering.publish")

    def archive(self, **kwargs: object):
        raise FeatureNotImplemented("CourseOffering.archive")

    def restore(self, **kwargs: object):
        raise FeatureNotImplemented("CourseOffering.restore")


@dataclass
class CourseMembership:
    membership_id: int
    offering_id: int
    user_id: int
    course_role: str
    status: str
    version: int

    def is_active(self, **kwargs: object):
        raise FeatureNotImplemented("CourseMembership.is_active")


@dataclass
class Topic:
    topic_id: int
    offering_id: int
    title: str
    position: int

    def rename(self, **kwargs: object):
        raise FeatureNotImplemented("Topic.rename")


@dataclass
class Material:
    material_id: int
    topic_id: int
    title: str
    kind: str
    status: str
    is_mandatory: bool

    def publish(self, **kwargs: object):
        raise FeatureNotImplemented("Material.publish")


@dataclass
class Assignment:
    assignment_id: int
    offering_id: int
    topic_id: int | None
    open_at: datetime
    due_at: datetime
    cutoff_at: datetime
    max_score: Decimal
    is_group_work: bool

    def is_open(self, **kwargs: object):
        raise FeatureNotImplemented("Assignment.is_open")

    def is_late(self, **kwargs: object):
        raise FeatureNotImplemented("Assignment.is_late")

    def publish(self, **kwargs: object):
        raise FeatureNotImplemented("Assignment.publish")


@dataclass
class AssignmentGroup:
    group_id: int
    assignment_id: int
    version: int
    member_ids: list[int] = field(default_factory=list)

    def add_member(self, **kwargs: object):
        raise FeatureNotImplemented("AssignmentGroup.add_member")


@dataclass
class FileAsset:
    file_id: int
    offering_id: int
    uploaded_by: int
    purpose: str
    state: str
    expires_at: datetime
    private_key: str


@dataclass
class Submission:
    submission_id: int
    assignment_id: int
    owner_type: str
    student_id: int | None
    group_id: int | None
    status: str
    version: int
    frozen_member_ids: list[int] = field(default_factory=list)

    def latest_version(self, **kwargs: object):
        raise FeatureNotImplemented("Submission.latest_version")


@dataclass(frozen=True)
class SubmissionVersion:
    submission_id: int
    version_no: int
    submitted_by: int
    submitted_at: datetime
    receipt_code: str
    request_key: str
    request_hash: str
    file_ids: tuple[int, ...]


@dataclass
class Grade:
    grade_id: int
    submission_id: int
    version: int
    draft_revision_no: int | None = None
    published_revision_no: int | None = None

    def revise(self, **kwargs: object):
        raise FeatureNotImplemented("Grade.revise")

    def publish(self, **kwargs: object):
        raise FeatureNotImplemented("Grade.publish")


@dataclass(frozen=True)
class GradeRevision:
    grade_id: int
    revision_no: int
    source_version_no: int | None
    score: Decimal
    feedback: str | None
    is_missing_zero: bool
    reason: str | None


@dataclass
class Quiz:
    quiz_id: int
    offering_id: int
    open_at: datetime
    close_at: datetime
    duration_minutes: int
    max_score: Decimal

    def is_open(self, **kwargs: object):
        raise FeatureNotImplemented("Quiz.is_open")

    def publish(self, **kwargs: object):
        raise FeatureNotImplemented("Quiz.publish")


@dataclass
class Question:
    question_id: int
    prompt: str
    kind: str
    points: Decimal

    def check_answer(self, **kwargs: object):
        raise FeatureNotImplemented("Question.check_answer")


@dataclass(frozen=True)
class QuizSnapshotQuestion:
    quiz_question_id: int
    quiz_id: int
    source_question_id: int
    prompt: str
    correct_key: str
    explanation: str | None
    points: Decimal


@dataclass
class QuizAttempt:
    attempt_id: int
    quiz_id: int
    student_id: int
    ends_at: datetime
    version: int
    score: Decimal | None = None
    released_at: datetime | None = None

    def save_answer(self, **kwargs: object):
        raise FeatureNotImplemented("QuizAttempt.save_answer")

    def seal(self, **kwargs: object):
        raise FeatureNotImplemented("QuizAttempt.seal")

    def finalize_saved_answers(self, **kwargs: object):
        raise FeatureNotImplemented("QuizAttempt.finalize_saved_answers")


@dataclass
class Notification:
    notification_id: int
    recipient_id: int
    event_key: str
    is_read: bool

    def mark_read(self, **kwargs: object):
        raise FeatureNotImplemented("Notification.mark_read")
