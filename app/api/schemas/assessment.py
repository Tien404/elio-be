"""Submission boxes (assignments) and submissions. Responses follow the OpenAPI contract.

MVP differences: an assignment is a box inside a topic with title, due date and max score
(mode INDIVIDUAL, no weight, cutoffAt null = late work accepted and flagged); the request
only takes those fields. Submissions need no Idempotency-Key.
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field

from app.api.schemas.common import Id, Instant, PageMeta, RequestModel, ResponseModel, Version

Title = Annotated[str, Field(min_length=1, max_length=200)]
Status = Literal["DRAFT", "PUBLISHED"]


class AssignmentRequest(RequestModel):
    title: Title
    topicId: Id
    dueAt: Annotated[datetime, Field(description="e.g. 2026-11-30T23:59:00+07:00")]
    maxScore: Annotated[Decimal, Field(gt=0, max_digits=6, decimal_places=2)]
    status: Status
    instructions: Annotated[
        str | None, Field(max_length=2000, description="Short note; post details as a material")
    ] = None


class UpdateAssignmentRequest(RequestModel):
    title: Title | None = None
    dueAt: datetime | None = None
    status: Status | None = None


class Assignment(ResponseModel):
    id: Id
    offeringId: Id
    topicId: Id | None
    title: str
    instructions: str | None
    mode: Literal["INDIVIDUAL", "GROUP"]
    status: Literal["DRAFT", "PUBLISHED", "ARCHIVED"]
    openAt: Instant
    dueAt: Instant
    cutoffAt: Instant | None
    maxScore: float
    weight: float
    version: Version


class AssignmentPage(PageMeta):
    items: list[Assignment]


class SubmissionRequest(RequestModel):
    expectedVersion: Annotated[
        int, Field(ge=0, description="Version you last saw; 0 for the first submission")
    ]
    fileIds: Annotated[list[Id], Field(min_length=1, max_length=5)]


class SubmissionVersion(ResponseModel):
    submissionId: Id
    versionNo: int
    fileIds: list[Id]
    submittedByStudentId: Id
    submittedAt: Instant
    isLate: bool
    receiptCode: str


class Submission(ResponseModel):
    id: Id
    assignmentId: Id
    subjectType: Literal["STUDENT", "GROUP"]
    subjectId: Id
    recipientStudentIds: list[Id]
    currentVersion: SubmissionVersion | None
    version: int
    status: Literal["NOT_SUBMITTED", "SUBMITTED"]


class SubmissionPage(PageMeta):
    items: list[Submission]
