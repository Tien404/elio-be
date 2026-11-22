"""Executable contracts for the personal projections added to main."""

from typing import Literal

from app.api.schemas.common import Id, Instant, PageMeta, ResponseModel
from app.api.schemas.offerings import Offering
from app.api.schemas.reports import Notification
from app.api.schemas.views import Dashboard


class ChecklistItem(ResponseModel):
    id: str
    kind: Literal["MATERIAL", "ASSIGNMENT", "QUIZ"]
    title: str
    complete: bool
    reason: str
    href: str


class ProgressRow(ResponseModel):
    offeringId: Id
    membershipId: Id
    studentId: Id
    displayName: str
    completed: int
    total: int
    percent: int | None
    notice: Literal["NO_MANDATORY_ACTIVITIES"] | None
    items: list[ChecklistItem]


class ProgressPage(PageMeta):
    items: list[ProgressRow]


class ProgressView(ResponseModel):
    teacher: bool
    rows: ProgressPage


class CalendarEvent(ResponseModel):
    id: str
    offeringId: Id
    activityId: Id
    title: str
    section: str
    kind: Literal["ASSIGNMENT_DUE", "QUIZ_OPEN", "QUIZ_CLOSE"]
    at: Instant
    opensAt: Instant | None
    endsAt: Instant
    status: Literal["PUBLISHED"]
    targetUri: str


class CalendarPage(PageMeta):
    serverNow: Instant
    items: list[CalendarEvent]


class InboxItem(Notification):
    event: str
    targetKind: str
    preview: str
    status: Literal["READ", "UNREAD"]
    href: str


class InboxRows(PageMeta):
    items: list[InboxItem]


class InboxView(InboxRows):
    unread: int
    unreadCount: int
    rows: InboxRows


class DashboardTask(ResponseModel):
    id: str
    kind: Literal["ASSIGNMENT", "QUIZ", "GRADING"]
    title: str
    detail: str
    at: Instant | None = None
    href: str


class DashboardAnnouncement(ResponseModel):
    id: Id
    offeringId: Id
    title: str
    href: str


class PersonalDashboard(Dashboard):
    sections: list[Offering]
    progress: list[ProgressRow]
    tasks: list[DashboardTask]
    announcements: list[DashboardAnnouncement]
    unread: int
    upcoming: list[CalendarEvent]
