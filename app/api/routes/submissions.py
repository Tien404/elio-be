from fastapi import APIRouter, Path

from app.services.submission_service import SubmissionService

router = APIRouter(tags=["submissions"], responses={400: {"description": "Invalid request"}})


@router.get(
    "/assignments/{assignmentId}/submissions", operation_id="listSubmissions", status_code=501
)
def list_submissions(assignmentId: int = Path(ge=1, le=2147483647)):
    return SubmissionService().list_submissions(assignment_id=assignmentId)


@router.post(
    "/assignments/{assignmentId}/submissions", operation_id="confirmSubmission", status_code=501
)
def confirm_submission(assignmentId: int = Path(ge=1, le=2147483647)):
    return SubmissionService().confirm(assignment_id=assignmentId)


@router.get("/submissions/{submissionId}", operation_id="getSubmission", status_code=501)
def get_submission(submissionId: int = Path(ge=1, le=2147483647)):
    return SubmissionService().get_submission(submission_id=submissionId)


@router.get(
    "/assignments/{assignmentId}/submission-receipts/{requestKey}",
    operation_id="getSubmissionReceipt",
    status_code=501,
)
def get_submission_receipt(
    assignmentId: int = Path(ge=1, le=2147483647),
    requestKey: str = Path(min_length=16, max_length=128),
):
    return SubmissionService().get_submission_receipt(
        assignment_id=assignmentId, request_key=requestKey
    )
