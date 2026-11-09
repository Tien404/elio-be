from typing import Annotated

from fastapi import APIRouter, Path, Query, Response

from app.api.dependencies import (
    ActorDep,
    MutationActorDep,
    SubmissionServiceDep,
    VersionDep,
    set_etag,
)
from app.api.schemas.assessment import (
    Assignment,
    AssignmentPage,
    AssignmentRequest,
    UpdateAssignmentRequest,
)

router = APIRouter(tags=["assignments"], responses={400: {"description": "Invalid request"}})

OfferingId = Annotated[int, Path(alias="offeringId", ge=1, le=2147483647)]
AssignmentId = Annotated[int, Path(alias="assignmentId", ge=1, le=2147483647)]


@router.get(
    "/offerings/{offeringId}/assignments",
    operation_id="listAssignments",
    response_model=AssignmentPage,
    summary="Submission boxes of a class by due date; students see PUBLISHED only.",
)
def list_assignments(
    offering_id: OfferingId,
    actor: ActorDep,
    service: SubmissionServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    pageSize: Annotated[int, Query(ge=1, le=100)] = 50,
):
    return service.list_assignments(
        actor=actor, offering_id=offering_id, page=page, page_size=pageSize
    )


@router.post(
    "/offerings/{offeringId}/assignments",
    operation_id="createAssignment",
    status_code=201,
    response_model=Assignment,
    summary="Class professor adds a submission box (title, due date, max score) to a topic.",
    responses={422: {"description": "TOPIC_NOT_FOUND"}},
)
def create_assignment(
    offering_id: OfferingId,
    body: AssignmentRequest,
    actor: MutationActorDep,
    response: Response,
    service: SubmissionServiceDep,
):
    view = service.save_assignment(
        actor=actor,
        offering_id=offering_id,
        data=body.model_dump(),
    )
    response.headers["Location"] = f"/api/v1/assignments/{view['id']}"
    set_etag(response, view["version"])
    return view


@router.get("/assignments/{assignmentId}", operation_id="getAssignment", response_model=Assignment)
def get_assignment(
    assignment_id: AssignmentId,
    actor: ActorDep,
    response: Response,
    service: SubmissionServiceDep,
):
    view = service.get_assignment(actor=actor, assignment_id=assignment_id)
    set_etag(response, view["version"])
    return view


@router.patch(
    "/assignments/{assignmentId}",
    operation_id="updateAssignment",
    response_model=Assignment,
    summary="Rename, move the due date or publish a box. Needs If-Match.",
    responses={412: {"description": "VERSION_CONFLICT"}},
)
def update_assignment(
    assignment_id: AssignmentId,
    body: UpdateAssignmentRequest,
    actor: MutationActorDep,
    version: VersionDep,
    response: Response,
    service: SubmissionServiceDep,
):
    view = service.update_assignment(
        actor=actor,
        assignment_id=assignment_id,
        expected_version=version,
        changes=body.model_dump(exclude_unset=True),
    )
    set_etag(response, view["version"])
    return view
