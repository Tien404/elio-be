from typing import Annotated

from fastapi import APIRouter, Path, Response

from app.api.dependencies import ActorDep, GroupServiceDep, MutationActorDep
from app.api.schemas.groups import Group, GroupList, GroupRequest, UpdateGroupRequest

router = APIRouter(tags=["groups"], responses={400: {"description": "Invalid request"}})

AssignmentId = Annotated[int, Path(alias="assignmentId", ge=1, le=2147483647)]
GroupId = Annotated[int, Path(alias="groupId", ge=1, le=2147483647)]


@router.get(
    "/assignments/{assignmentId}/groups",
    operation_id="listGroups",
    response_model=GroupList,
    summary="Groups of a group assignment (with members), and the caller's group.",
    responses={409: {"description": "NOT_GROUP_WORK"}},
)
def list_groups(assignment_id: AssignmentId, actor: ActorDep, service: GroupServiceDep):
    return service.list_groups(actor=actor, assignment_id=assignment_id)


@router.post(
    "/assignments/{assignmentId}/groups",
    operation_id="createGroup",
    status_code=201,
    response_model=Group,
    summary="Student: create a group and be put in it. Professor: create a group with members.",
    responses={409: {"description": "ALREADY_IN_GROUP, GROUP_NAME_TAKEN or ALREADY_GRADED"}},
)
def create_group(
    assignment_id: AssignmentId,
    body: GroupRequest,
    actor: MutationActorDep,
    service: GroupServiceDep,
):
    return service.create_group(
        actor=actor, assignment_id=assignment_id, name=body.name, member_ids=body.memberIds
    )


@router.get("/groups/{groupId}", operation_id="getGroup", response_model=Group)
def get_group(group_id: GroupId, actor: ActorDep, service: GroupServiceDep):
    return service.get_group(actor=actor, group_id=group_id)


@router.patch(
    "/groups/{groupId}",
    operation_id="updateGroup",
    response_model=Group,
    summary="Professor renames a group or sets its members (not after it submitted).",
    responses={409: {"description": "GROUP_LOCKED or ALREADY_IN_GROUP"}},
)
def update_group(
    group_id: GroupId, body: UpdateGroupRequest, actor: MutationActorDep, service: GroupServiceDep
):
    return service.update_group(
        actor=actor, group_id=group_id, name=body.name, member_ids=body.memberIds
    )


@router.post(
    "/groups/{groupId}/membership",
    operation_id="joinGroup",
    response_model=Group,
    summary="Student joins a group with space (leave your current group first).",
    responses={409: {"description": "GROUP_NOT_JOINABLE or ALREADY_IN_GROUP"}},
)
def join_group(group_id: GroupId, actor: MutationActorDep, service: GroupServiceDep):
    return service.join_group(actor=actor, group_id=group_id)


@router.delete(
    "/groups/{groupId}/membership",
    operation_id="leaveGroup",
    status_code=204,
    summary="Student leaves their group (not after it submitted); an empty group is removed.",
    responses={409: {"description": "GROUP_NOT_LEAVABLE"}},
)
def leave_group(group_id: GroupId, actor: MutationActorDep, service: GroupServiceDep):
    service.leave_group(actor=actor, group_id=group_id)
    return Response(status_code=204)
