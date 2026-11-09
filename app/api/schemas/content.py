from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.api.schemas.common import Id, Instant, PageMeta, RequestModel, ResponseModel, Version

Title = Annotated[str, Field(min_length=1, max_length=200)]
Status = Literal["DRAFT", "PUBLISHED", "ARCHIVED"]


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
    body: str | None = None
    mandatory: bool = False
    title: Title
    topicId: Id
    kind: Literal["FILE", "LINK", "TEXT"]
    status: Status
    externalUrl: Annotated[str | None, Field(max_length=2048)] = None
    fileIds: Annotated[list[Id] | None, Field(max_length=1)] = None


class UpdateResourceRequest(RequestModel):
    topicId: Id | None = None
    kind: Literal["FILE", "LINK", "TEXT"] | None = None
    body: str | None = None
    externalUrl: Annotated[str | None, Field(max_length=2048)] = None
    fileIds: Annotated[list[Id] | None, Field(max_length=1)] = None
    mandatory: bool | None = None
    title: Title | None = None
    status: Status | None = None

    @model_validator(mode="after")
    def nonnullable(self):
        for name in self.model_fields_set - {"body", "externalUrl"}:
            if getattr(self, name) is None:
                raise ValueError(f"{name} must not be null")
        return self


class Resource(ResponseModel):
    mandatory: bool
    completed: bool
    files: list[FileAsset]
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
