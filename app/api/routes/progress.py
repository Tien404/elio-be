from fastapi import APIRouter, Path

from app.services.course_service import CourseService

router = APIRouter(tags=["progress"], responses={400: {"description": "Invalid request"}})


@router.put(
    "/resources/{resourceId}/completion", operation_id="markResourceComplete", status_code=501
)
def mark_resource_complete(resourceId: int = Path(ge=1, le=2147483647)):
    return CourseService().mark_resource_complete(resource_id=resourceId)


@router.delete(
    "/resources/{resourceId}/completion", operation_id="unmarkResourceComplete", status_code=501
)
def unmark_resource_complete(resourceId: int = Path(ge=1, le=2147483647)):
    return CourseService().unmark_resource_complete(resource_id=resourceId)


@router.get("/offerings/{offeringId}/progress", operation_id="getCourseProgress", status_code=501)
def get_course_progress(offeringId: int = Path(ge=1, le=2147483647)):
    return CourseService().get_course_progress(offering_id=offeringId)
