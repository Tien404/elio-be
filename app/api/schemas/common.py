"""Shared DTO building blocks. Field names follow the OpenAPI contract (camelCase)."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

Id = Annotated[int, Field(ge=1, le=2147483647)]
Version = Annotated[int, Field(ge=1)]
Email = Annotated[str, Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]
Reason = Annotated[str, Field(min_length=1, max_length=1000)]


def utc_datetime(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def utc_payload(value):
    if isinstance(value, datetime):
        return utc_datetime(value)
    if isinstance(value, dict):
        return {key: utc_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [utc_payload(item) for item in value]
    return value


Instant = Annotated[datetime, AfterValidator(utc_datetime)]


class RequestModel(BaseModel):
    """Requests reject unknown fields (additionalProperties: false)."""

    model_config = ConfigDict(extra="forbid")


class ResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ActionResult(ResponseModel):
    status: Literal["ACCEPTED", "COMPLETED"]
    resourceId: Id | None


class PageMeta(ResponseModel):
    page: int
    pageSize: int
    totalItems: int
    totalPages: int


PageQuery = Annotated[int, Field(ge=1)]
PageSizeQuery = Annotated[int, Field(ge=1, le=100)]
