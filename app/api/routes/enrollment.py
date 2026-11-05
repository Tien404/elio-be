from fastapi import APIRouter, Path

from app.services.course_service import CourseService

router = APIRouter(tags=["enrollment"], responses={400: {"description": "Invalid request"}})


@router.post("/offerings/{offeringId}/enrollments", operation_id="joinCourse", status_code=501)
def join_course(offeringId: int = Path(ge=1, le=2147483647)):
    return CourseService().join_by_code(offering_id=offeringId)


@router.get("/offerings/{offeringId}/memberships", operation_id="listMemberships", status_code=501)
def list_memberships(offeringId: int = Path(ge=1, le=2147483647)):
    return CourseService().list_memberships(offering_id=offeringId)
