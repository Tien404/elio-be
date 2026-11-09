from typing import Literal

from app.api.schemas.assessment import Submission, SubmissionVersion
from app.api.schemas.common import Id, Instant, PageMeta, ResponseModel, Version
from app.api.schemas.content import FileAsset
from app.api.schemas.identity import AccountSummary


class AccountSummaryPage(PageMeta):
    items: list[AccountSummary]


class OfferingSummary(ResponseModel):
    id: Id
    courseId: Id
    courseCode: str
    title: str
    semester: str
    sectionCode: str
    status: Literal["DRAFT", "OPEN", "ARCHIVED"]
    leadMembershipId: Id
    version: Version


class DashboardAssignment(ResponseModel):
    id: Id
    offeringId: Id
    title: str
    dueAt: Instant
    cutoffAt: Instant
    submitted: bool


class Dashboard(ResponseModel):
    serverNow: Instant
    role: Literal["STUDENT", "INSTRUCTOR", "ADMIN"]
    counts: dict[str, int | None]
    sections: list[OfferingSummary]
    assignments: list[DashboardAssignment]


class SubmissionHistory(ResponseModel):
    submission: Submission
    history: list[SubmissionVersion]
    files: list[FileAsset]
    recipients: list[AccountSummary]
    grade: None = None
    revisions: list[dict] = []
