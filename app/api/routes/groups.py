from fastapi import APIRouter, Path

from app.services.submission_service import SubmissionService

router = APIRouter(tags=["groups"], responses={400: {"description": "Invalid request"}})


@router.get("/assignments/{assignmentId}/groups", operation_id="listGroups", status_code=501)
def list_groups(assignmentId: int = Path(ge=1, le=2147483647)):
    return SubmissionService().list_groups(assignment_id=assignmentId)


@router.post("/assignments/{assignmentId}/groups", operation_id="createGroup", status_code=501)
def create_group(assignmentId: int = Path(ge=1, le=2147483647)):
    return SubmissionService().create_group(assignment_id=assignmentId)


@router.get("/groups/{groupId}", operation_id="getGroup", status_code=501)
def get_group(groupId: int = Path(ge=1, le=2147483647)):
    return SubmissionService().get_group(group_id=groupId)


@router.patch("/groups/{groupId}", operation_id="updateGroup", status_code=501)
def update_group(groupId: int = Path(ge=1, le=2147483647)):
    return SubmissionService().update_group(group_id=groupId)
