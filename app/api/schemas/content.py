"""Topics, files and materials ("resources"). Shapes follow the OpenAPI contract.

MVP differences: TopicRequest.position is optional (next free position), materials are
FILE or LINK only, and UpdateResourceRequest only changes title and/or status.
"""

from typing import Annotated, Literal

from pydantic import Field

from app.api.schemas.common import Id, Instant, PageMeta, RequestModel, ResponseModel, Version

Title = Annotated[str, Field(min_length=1, max_length=200)]
Status = Literal["DRAFT", "PUBLISHED"]


class TopicRequest(RequestModel):
    title: Title
    position: Annotated[int | None, Field(ge=1, description="Default: after the last")] = None


class Topic(ResponseModel):
    id: Id
    offeringId: Id
    title: str
    position: int
    version: Version


class TopicPage(PageMeta):
    items: list[Topic]


class FileAsset(ResponseModel):
    id: Id
    offeringId: Id
    originalName: str
    mediaType: str
    byteSize: int
    sha256: str
    state: Literal["STAGING", "ATTACHED", "EXPIRED"]
    leaseExpiresAt: Instant
    purpose: Literal["MATERIAL", "ASSIGNMENT_ATTACHMENT", "SUBMISSION"]


class ResourceRequest(RequestModel):
    title: Title
    topicId: Id
    kind: Literal["FILE", "LINK"]
    status: Status
    externalUrl: Annotated[str | None, Field(max_length=2048)] = None
    fileIds: Annotated[list[Id] | None, Field(max_length=1)] = None


class UpdateResourceRequest(RequestModel):
    title: Title | None = None
    status: Status | None = None


class Resource(ResponseModel):
    id: Id
    offeringId: Id
    topicId: Id
    title: str
    kind: Literal["FILE", "TEXT", "LINK"]
    status: Literal["DRAFT", "PUBLISHED", "ARCHIVED"]
    body: str | None
    externalUrl: str | None
    fileIds: list[Id]
    version: Version


class ResourcePage(PageMeta):
    items: list[Resource]
