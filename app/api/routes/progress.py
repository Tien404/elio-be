from typing import Annotated

from fastapi import APIRouter, Path, Response

from app.api.dependencies import ContentServiceDep, MutationActorDep
from app.api.schemas.content import Resource
from app.services.course_service import CourseService

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


@router.get("/offerings/{offeringId}/progress", operation_id="getCourseProgress", status_code=501)
def get_course_progress(offeringId: int = Path(ge=1, le=2147483647)):
    return CourseService().get_course_progress(offering_id=offeringId)
