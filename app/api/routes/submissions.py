from typing import Annotated

from fastapi import APIRouter, Header, Path, Query, Response

from app.api.dependencies import ActorDep, MutationActorDep, SubmissionServiceDep
from app.api.schemas.assessment import (
    Submission,
    SubmissionPage,
    SubmissionRequest,
    SubmissionVersion,
)
from app.api.schemas.views import SubmissionHistory

router = APIRouter(tags=["submissions"], responses={400: {"description": "Invalid request"}})

AssignmentId = Annotated[int, Path(alias="assignmentId", ge=1, le=2147483647)]


@router.get(
    "/assignments/{assignmentId}/submissions",
    operation_id="listSubmissions",
    response_model=SubmissionPage,
    summary="Class professor: submitted work for a box (newest version of each student).",
)
def list_submissions(
    assignment_id: AssignmentId,
    actor: ActorDep,
    service: SubmissionServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    pageSize: Annotated[int, Query(ge=1, le=100)] = 50,
):
    return service.list_submissions(
        actor=actor, assignment_id=assignment_id, page=page, page_size=pageSize
    )


@router.post(
    "/assignments/{assignmentId}/submissions",
    operation_id="confirmSubmission",
    status_code=201,
    response_model=Submission,
    summary="Student submits uploaded files (POST /files purpose=SUBMISSION) as a new version.",
    responses={
        412: {"description": "VERSION_CONFLICT (submitted from another tab meanwhile)"},
        422: {"description": "FILE_NOT_USABLE"},
    },
)
def confirm_submission(
    assignment_id: AssignmentId,
    body: SubmissionRequest,
    actor: MutationActorDep,
    response: Response,
    service: SubmissionServiceDep,
    request_key: Annotated[
        str, Header(alias="Idempotency-Key", pattern=r"^[A-Za-z0-9._:-]{16,128}$")
    ],
):
    view = service.confirm_submission(
        actor=actor,
        assignment_id=assignment_id,
        expected_version=body.expectedVersion,
        file_ids=body.fileIds,
        request_key=request_key,
        group_id=body.groupId,
    )
    response.headers["Location"] = f"/api/v1/submissions/{view['id']}"
    return view


@router.get(
    "/assignments/{assignmentId}/submissions/me",
    operation_id="getMySubmission",
    response_model=Submission,
    summary="Student: my submission for this box (404 NOT_SUBMITTED if none yet).",
)
def get_my_submission(assignment_id: AssignmentId, actor: ActorDep, service: SubmissionServiceDep):
    return service.get_my_submission(actor=actor, assignment_id=assignment_id)


@router.get("/submissions/{submissionId}", operation_id="getSubmission", response_model=Submission)
def get_submission(
    submission_id: Annotated[int, Path(alias="submissionId", ge=1, le=2147483647)],
    actor: ActorDep,
    service: SubmissionServiceDep,
):
    return service.get_submission(actor=actor, submission_id=submission_id)


@router.get(
    "/assignments/{assignmentId}/submission-receipts/{requestKey}",
    operation_id="getSubmissionReceipt",
    response_model=SubmissionVersion,
    summary="Recover the original actor-owned confirmation by its Idempotency-Key.",
)
def get_submission_receipt(
    assignment_id: AssignmentId,
    request_key: Annotated[str, Path(alias="requestKey", min_length=16, max_length=128)],
    actor: ActorDep,
    service: SubmissionServiceDep,
):
    return service.get_submission_receipt(actor=actor, assignment_id=assignment_id, key=request_key)


@router.get(
    "/submissions/{submissionId}/history",
    operation_id="getSubmissionHistory",
    response_model=SubmissionHistory,
)
def get_submission_history(
    submissionId: Annotated[int, Path(ge=1, le=2147483647)],
    actor: ActorDep,
    service: SubmissionServiceDep,
):
    return service.get_submission_history(actor=actor, submission_id=submissionId)
