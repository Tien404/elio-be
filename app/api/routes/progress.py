from typing import Annotated

from fastapi import APIRouter, Path, Query, Response

from app.api.dependencies import (
    ActorDep,
    ContentServiceDep,
    DatabaseDep,
    MutationActorDep,
)
from app.api.schemas.content import Resource
from app.api.schemas.personal import ProgressView
from app.services.personal_service import PersonalService

router = APIRouter(tags=["progress"], responses={400: {"description": "Invalid request"}})


@router.put(
    "/resources/{resourceId}/completion",
    operation_id="markResourceComplete",
    response_model=Resource,
)
def mark_resource_complete(
    resourceId: Annotated[int, Path(ge=1, le=2147483647)],
    actor: MutationActorDep,
    service: ContentServiceDep,
):
    return service.set_completion(actor=actor, material_id=resourceId, complete=True)


@router.delete(
    "/resources/{resourceId}/completion",
    operation_id="unmarkResourceComplete",
    status_code=204,
)
def unmark_resource_complete(
    resourceId: Annotated[int, Path(ge=1, le=2147483647)],
    actor: MutationActorDep,
    service: ContentServiceDep,
):
    service.set_completion(actor=actor, material_id=resourceId, complete=False)
    return Response(status_code=204)


@router.get(
    "/offerings/{offeringId}/progress",
    operation_id="getCourseProgress",
    response_model=ProgressView,
    summary="Class professor: each student's materials done, work submitted, quizzes taken.",
)
def get_course_progress(
    offeringId: Annotated[int, Path(ge=1, le=2147483647)],
    actor: ActorDep,
    database: DatabaseDep,
    page: Annotated[int, Query(ge=1)] = 1,
    pageSize: Annotated[int, Query(ge=1, le=100)] = 25,
    search: str | None = None,
    state: str = "ALL",
):
    return PersonalService(database).progress(
        actor=actor,
        offering_id=offeringId,
        page=page,
        page_size=pageSize,
        search=search,
        state=state,
    )
