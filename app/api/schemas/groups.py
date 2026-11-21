"""Groups for group assignments."""

from typing import Annotated

from pydantic import Field

from app.api.schemas.common import Id, RequestModel, ResponseModel, Version

GroupName = Annotated[str, Field(min_length=1, max_length=120)]


class GroupRequest(RequestModel):
    name: GroupName
    memberIds: Annotated[list[Id], Field(max_length=20)] | None = Field(
        default=None, description="Professor only; students are put in the group they create"
    )


class UpdateGroupRequest(RequestModel):
    name: GroupName | None = None
    memberIds: Annotated[list[Id], Field(max_length=20)] | None = None


class GroupMember(ResponseModel):
    id: Id
    displayName: str
    studentCode: str


class Group(ResponseModel):
    id: Id
    assignmentId: Id
    name: str
    members: list[GroupMember]
    size: int
    maxSize: int
    locked: bool = Field(description="The group has submitted; members are fixed")
    version: Version


class GroupList(ResponseModel):
    assignmentId: Id
    maxGroupSize: int
    myGroupId: Id | None
    items: list[Group]
