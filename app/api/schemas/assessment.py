from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from app.api.schemas.common import Id, Instant, PageMeta, RequestModel, ResponseModel, Version
from app.api.schemas.content import FileAsset

Title = Annotated[str, Field(min_length=1, max_length=200)]


class AssignmentRequest(RequestModel):
    title: Title
    topicId: Id | None = None
    instructions: str | None = None
    mode: Literal["INDIVIDUAL"] = "INDIVIDUAL"
    status: Literal["DRAFT", "PUBLISHED"]
    openAt: AwareDatetime
    dueAt: AwareDatetime
    cutoffAt: AwareDatetime
    maxScore: Annotated[Decimal, Field(gt=0, max_digits=6, decimal_places=2)]
    weight: Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)] = Decimal(0)
    fileIds: Annotated[list[Id], Field(max_length=5)] = []
    mandatory: bool = False

    @model_validator(mode="after")
    def schedule(self):
        if not self.openAt <= self.dueAt <= self.cutoffAt:
            raise ValueError("openAt <= dueAt <= cutoffAt required")
        if len(set(self.fileIds)) != len(self.fileIds):
            raise ValueError("Duplicate attachment")
        return self


class UpdateAssignmentRequest(RequestModel):
    title: Title | None = None
    topicId: Id | None = None
    instructions: str | None = None
    mode: Literal["INDIVIDUAL"] | None = None
    status: Literal["DRAFT", "PUBLISHED", "ARCHIVED"] | None = None
    openAt: AwareDatetime | None = None
    dueAt: AwareDatetime | None = None
    cutoffAt: AwareDatetime | None = None
    maxScore: Annotated[Decimal, Field(gt=0, max_digits=6, decimal_places=2)] | None = None
    weight: Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)] | None = None
    fileIds: Annotated[list[Id], Field(max_length=5)] | None = None
    mandatory: bool | None = None

    @model_validator(mode="after")
    def nonnullable(self):
        for name in self.model_fields_set - {"topicId", "instructions"}:
            if getattr(self, name) is None:
                raise ValueError(f"{name} must not be null")
        return self


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
    cutoffAt: Instant
    maxScore: float
    weight: float
    version: Version
    mandatory: bool
    attachments: list[FileAsset]
    serverNow: Instant


class AssignmentPage(PageMeta):
    items: list[Assignment]


class SubmissionRequest(RequestModel):
    expectedVersion: Annotated[int, Field(ge=0)]
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
