from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.api.schemas.common import Email, Id, PageMeta, RequestModel, ResponseModel, Version
from app.api.schemas.identity import AccountSummary


class CreateOfferingRequest(RequestModel):
    courseCode: Annotated[str, Field(min_length=1, max_length=40)]
    semester: Annotated[str, Field(min_length=1, max_length=40)]
    sectionCode: Annotated[str, Field(min_length=1, max_length=40)]
    title: Annotated[str, Field(min_length=1, max_length=200)]
    instructorEmail: Email | None = None
    learningInformation: Annotated[str, Field(max_length=10000)] = ""


class UpdateOfferingRequest(RequestModel):
    title: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    semester: Annotated[str, Field(min_length=1, max_length=40)] | None = None
    sectionCode: Annotated[str, Field(min_length=1, max_length=40)] | None = None
    learningInformation: Annotated[str, Field(max_length=10000)] | None = None
    status: Literal["DRAFT", "OPEN", "ARCHIVED"] | None = None
    joinCodeAction: Literal["rotate", "disable"] | None = None
    reason: Annotated[str, Field(min_length=1, max_length=1000)] | None = None


class RestoreOfferingRequest(RequestModel):
    reason: Annotated[str, Field(min_length=1, max_length=1000)]


class EnrollStudentRequest(RequestModel):
    email: Email | None = None
    accountId: Id | None = None
    code: Annotated[str, Field(pattern=r"^[A-Za-z0-9]{6}$")] | None = None

    @model_validator(mode="after")
    def one_target(self):
        if sum(x is not None for x in [self.email, self.accountId, self.code]) != 1:
            raise ValueError("Provide code, accountId or email")
        return self


class JoinCodeRequest(RequestModel):
    code: Annotated[str, Field(pattern=r"^[A-Za-z0-9]{6}$")]


class Membership(ResponseModel):
    id: Id
    offeringId: Id
    account: AccountSummary
    role: Literal["STUDENT", "INSTRUCTOR"]
    teachingRole: Literal["LEAD", "CO_INSTRUCTOR"] | None
    status: Literal["ACTIVE", "REMOVED"]
    version: Version


class MembershipPage(PageMeta):
    items: list[Membership]


class Offering(ResponseModel):
    id: Id
    courseId: Id
    courseCode: str
    title: str
    semester: str
    sectionCode: str
    status: Literal["DRAFT", "OPEN", "ARCHIVED"]
    leadMembershipId: Id
    version: Version
    permissions: dict[str, bool]
    lead: AccountSummary | None
    teachingRole: Literal["LEAD", "CO_INSTRUCTOR"] | None
    learningInformation: str | None
    joinCode: str | None
    joinEnabled: bool
    completedMaterials: int
    totalMaterials: int


class OfferingPage(PageMeta):
    items: list[Offering]
