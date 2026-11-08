"""Catalog courses (team MVP flow). CatalogCourse matches the OpenAPI contract shape."""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field

from app.api.schemas.common import Id, RequestModel, ResponseModel

DegreeLevel = Literal["UNDERGRADUATE", "MASTERS", "PHD"]


class CatalogCourse(ResponseModel):
    id: Id
    courseCode: str
    courseName: str
    credits: float


class CreateCatalogCourseRequest(RequestModel):
    """The course code is generated: facultyCode + yearLevel + degree digit + next number."""

    facultyCode: Annotated[
        str, Field(pattern=r"^[A-Za-z]{2,4}$", description="Faculty prefix, e.g. CS")
    ]
    yearLevel: Annotated[int, Field(ge=1, le=9, description="Year the course is meant for")]
    degreeLevel: Annotated[
        DegreeLevel, Field(description="UNDERGRADUATE -> 0, MASTERS -> 1, PHD -> 2")
    ]
    courseName: Annotated[str, Field(min_length=1, max_length=200)]
    credits: Annotated[Decimal, Field(gt=0, max_digits=3, decimal_places=1)]
    description: Annotated[str | None, Field(max_length=4000)] = None
