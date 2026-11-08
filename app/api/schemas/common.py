"""Shared DTO building blocks. Field names follow the OpenAPI contract (camelCase)."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Id = Annotated[int, Field(ge=1, le=2147483647)]
Version = Annotated[int, Field(ge=1)]
Email = Annotated[str, Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]
Reason = Annotated[str, Field(min_length=1, max_length=1000)]
Instant = datetime


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
