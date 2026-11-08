"""Classes (course offerings). Offering matches the OpenAPI contract shape.

CreateOfferingRequest differs from the contract (team MVP flow): the section code is
generated, and an admin names the professor with instructorEmail.
"""

from typing import Annotated, Literal

from pydantic import Field

from app.api.schemas.common import Email, Id, PageMeta, RequestModel, ResponseModel, Version
from app.api.schemas.identity import AccountSummary


class CreateOfferingRequest(RequestModel):
    courseCode: Annotated[str, Field(min_length=1, max_length=40, description="e.g. CS1001")]
    semester: Annotated[str, Field(min_length=1, max_length=40, description="e.g. 2026-1")]
    title: Annotated[str, Field(min_length=1, max_length=200)]
    instructorEmail: Annotated[
        Email | None,
        Field(description="Admins: the professor. Instructors: leave out (they lead it)."),
    ] = None


class EnrollStudentRequest(RequestModel):
    """Contract gap API-G01: the professor adds an approved student by email."""

    email: Email


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


class OfferingPage(PageMeta):
    items: list[Offering]
