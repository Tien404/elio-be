"""Read-only overviews: admin class list, audit log, progress and calendar."""

from typing import Any, Literal

from pydantic import Field

from app.api.schemas.common import Id, Instant, PageMeta, ResponseModel


class Person(ResponseModel):
    id: Id
    displayName: str


class AdminClass(ResponseModel):
    id: Id
    courseCode: str
    courseName: str
    title: str
    semester: str
    sectionCode: str
    status: Literal["DRAFT", "OPEN", "ARCHIVED"]
    lead: Person | None
    studentCount: int


class AdminClassPage(PageMeta):
    items: list[AdminClass]


class AuditEntry(ResponseModel):
    id: Id
    actor: Person
    action: str
    targetType: str
    targetId: int
    reason: str | None
    details: dict[str, Any]
    createdAt: Instant


class AuditPage(PageMeta):
    items: list[AuditEntry]


class Count(ResponseModel):
    done: int
    total: int


class ProgressStudent(ResponseModel):
    id: Id
    displayName: str
    studentCode: str


class StudentProgress(ResponseModel):
    student: ProgressStudent
    materials: Count = Field(description="Published materials marked done")
    assignments: Count = Field(description="Published assignments submitted")
    quizzes: Count = Field(description="Published quizzes with a finished attempt")
    percent: float | None = Field(description="All done / all published; null if nothing yet")


class ClassProgress(ResponseModel):
    offeringId: Id
    courseCode: str
    title: str
    students: list[StudentProgress]


class MyClassProgress(StudentProgress):
    offeringId: Id
    courseCode: str
    title: str


class MyProgress(ResponseModel):
    items: list[MyClassProgress]


class CalendarItem(ResponseModel):
    activityId: Id
    type: Literal["ASSIGNMENT", "QUIZ"]
    offeringId: Id
    courseCode: str
    classTitle: str
    title: str
    opensAt: Instant | None = Field(description="Quizzes: when it opens")
    dueAt: Instant = Field(description="Assignment due date or quiz closing time")
    done: bool | None = Field(description="Students: submitted / attempted; null for professors")


class Calendar(ResponseModel):
    from_: Instant = Field(alias="from")
    to: Instant
    serverNow: Instant
    items: list[CalendarItem]


class Notification(ResponseModel):
    id: Id
    eventType: Literal[
        "ANNOUNCEMENT",
        "ASSIGNMENT_PUBLISHED",
        "DUE_DATE_CHANGED",
        "GRADES_RELEASED",
        "QUIZ_PUBLISHED",
        "QUIZ_RESULT_RELEASED",
        "INSTRUCTOR_ADDED",
        "LEAD_TRANSFERRED",
    ]
    message: str
    offeringId: Id | None
    targetType: str = Field(description="What to open: ANNOUNCEMENT or ASSIGNMENT")
    targetId: int
    actor: Person | None
    read: bool
    createdAt: Instant


class NotificationPage(PageMeta):
    items: list[Notification]
    unreadCount: int
