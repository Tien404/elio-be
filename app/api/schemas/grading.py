"""Grade report page (same for student and professor) and the grade boxes."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.api.schemas.common import Id, RequestModel, ResponseModel

SpecialMarkName = Literal["ABSENT", "BANNED"]  # school codes 11 and 12, both count as 0
Feedback = Annotated[str, Field(max_length=10000)]


class GradeRequest(RequestModel):
    """Either a score (0..max) or a special mark, plus optional feedback."""

    score: Annotated[Decimal, Field(ge=0, max_digits=6, decimal_places=2)] | None = None
    specialMark: SpecialMarkName | None = None
    feedback: Feedback | None = None

    @model_validator(mode="after")
    def one_of(self):
        if (self.score is None) == (self.specialMark is None):
            raise ValueError("Give either score or specialMark")
        return self


class MissingWorkRequest(RequestModel):
    studentId: Id
    specialMark: SpecialMarkName
    feedback: Feedback | None = None


class GradeItem(ResponseModel):
    activityId: Id = Field(description="Assignment or quiz id (see type).")
    type: Literal["ASSIGNMENT", "QUIZ"]
    title: str
    weight: float | None
    grade: float | None
    specialMark: SpecialMarkName | None
    specialCode: Literal[11, 12] | None
    rangeMin: float
    rangeMax: float
    percentage: float | None
    feedback: str | None
    contribution: float | None
    status: Literal["NOT_GRADED", "DRAFT", "RELEASED"]
    submitted: bool
    submissionId: Id | None
    gradeId: Id | None


class GradeTotal(ResponseModel):
    rangeMin: float
    rangeMax: float
    grade: float | None
    percentage: float | None


class GradeStudent(ResponseModel):
    id: Id
    displayName: str
    studentCode: str


class GradeReport(ResponseModel):
    offeringId: Id
    courseCode: str
    title: str
    student: GradeStudent
    items: list[GradeItem]
    total: GradeTotal


class MyGrades(ResponseModel):
    items: list[GradeReport]


class GradeRelease(ResponseModel):
    assignmentId: Id
    released: int


class GradebookColumn(ResponseModel):
    activityId: Id
    type: Literal["ASSIGNMENT", "QUIZ"]
    title: str
    rangeMax: float
    weight: float | None


class GradebookRow(ResponseModel):
    student: GradeStudent
    items: list[GradeItem] = Field(description="Same order as columns")
    total: GradeTotal


class Gradebook(ResponseModel):
    offeringId: Id
    courseCode: str
    title: str
    semester: str
    sectionCode: str
    columns: list[GradebookColumn]
    total: GradeTotal = Field(description="Range of the course total")
    rows: list[GradebookRow]


class Reviser(ResponseModel):
    id: Id
    displayName: str


class GradeRevision(ResponseModel):
    revisionNo: int
    grade: float
    specialMark: SpecialMarkName | None
    specialCode: Literal[11, 12] | None
    feedback: str | None
    revisedBy: Reviser
    revisedAt: datetime


class GradeRecord(ResponseModel):
    id: Id
    submissionId: Id
    assignmentId: Id
    studentIds: list[Id]
    status: Literal["DRAFT", "RELEASED"]
    current: GradeRevision = Field(description="Professor: the draft. Student: the released one")
    released: GradeRevision | None
    revisions: list[GradeRevision] | None = Field(description="Edit history, professor only")
    version: int


class StudentGradeRow(ResponseModel):
    student: GradeStudent
    grade: GradeItem


class AssignmentGradeRecords(ResponseModel):
    assignmentId: Id
    title: str
    maxScore: float
    items: list[StudentGradeRow]
