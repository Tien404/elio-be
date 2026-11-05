from fastapi import APIRouter, Path

from app.services.submission_service import SubmissionService

router = APIRouter(tags=["assignments"], responses={400: {"description": "Invalid request"}})


@router.get("/offerings/{offeringId}/assignments", operation_id="listAssignments", status_code=501)
def list_assignments(offeringId: int = Path(ge=1, le=2147483647)):
    return SubmissionService().list_assignments(offering_id=offeringId)


@router.post(
    "/offerings/{offeringId}/assignments", operation_id="createAssignment", status_code=501
)
def create_assignment(offeringId: int = Path(ge=1, le=2147483647)):
    return SubmissionService().save_assignment(offering_id=offeringId)


@router.get("/assignments/{assignmentId}", operation_id="getAssignment", status_code=501)
def get_assignment(assignmentId: int = Path(ge=1, le=2147483647)):
    return SubmissionService().get_assignment(assignment_id=assignmentId)


@router.patch("/assignments/{assignmentId}", operation_id="updateAssignment", status_code=501)
def update_assignment(assignmentId: int = Path(ge=1, le=2147483647)):
    return SubmissionService().update_assignment(assignment_id=assignmentId)
