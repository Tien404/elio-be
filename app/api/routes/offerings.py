from fastapi import APIRouter, Path

from app.services.course_service import CourseService

router = APIRouter(tags=["offerings"], responses={400: {"description": "Invalid request"}})


@router.get("/offerings", operation_id="listCourses", status_code=501)
def list_courses():
    return CourseService().list_courses()


@router.post("/offerings", operation_id="createCourse", status_code=501)
def create_course():
    return CourseService().create_offering()


@router.get("/offerings/{offeringId}", operation_id="getCourse", status_code=501)
def get_course(offeringId: int = Path(ge=1, le=2147483647)):
    return CourseService().get_course(offering_id=offeringId)


@router.patch("/offerings/{offeringId}", operation_id="updateCourse", status_code=501)
def update_course(offeringId: int = Path(ge=1, le=2147483647)):
    return CourseService().update_course(offering_id=offeringId)


@router.post("/offerings/{offeringId}/restore", operation_id="restoreOffering", status_code=501)
def restore_offering(offeringId: int = Path(ge=1, le=2147483647)):
    return CourseService().restore_offering(offering_id=offeringId)


@router.get("/courses", operation_id="listCatalogCourses", status_code=501)
def list_catalog_courses():
    return CourseService().list_catalog_courses()
