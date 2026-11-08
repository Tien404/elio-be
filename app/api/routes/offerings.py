from typing import Annotated

from fastapi import APIRouter, Path, Query, Response

from app.api.dependencies import ActorDep, CourseServiceDep, MutationActorDep, set_etag
from app.api.schemas.catalog import CatalogCoursePage, StudentList
from app.api.schemas.offerings import CreateOfferingRequest, Offering, OfferingPage
from app.services.course_service import CourseService

router = APIRouter(tags=["offerings"], responses={400: {"description": "Invalid request"}})

OfferingId = Annotated[int, Path(alias="offeringId", ge=1, le=2147483647)]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


@router.get(
    "/offerings",
    operation_id="listCourses",
    response_model=OfferingPage,
    summary="My classes (students and professors); admins see every class.",
)
def list_courses(
    actor: ActorDep, service: CourseServiceDep, page: Page = 1, pageSize: PageSize = 25
):
    return service.list_my_offerings(actor=actor, page=page, page_size=pageSize)


@router.post(
    "/offerings",
    operation_id="createCourse",
    status_code=201,
    response_model=Offering,
    summary="Create a class of a catalog course (admin, or instructor with canCreateCourse).",
    responses={
        403: {"description": "FORBIDDEN"},
        404: {"description": "Course not found"},
        422: {"description": "INSTRUCTOR_NOT_FOUND"},
    },
)
def create_course(
    body: CreateOfferingRequest,
    actor: MutationActorDep,
    response: Response,
    service: CourseServiceDep,
):
    view = service.create_offering(
        actor=actor,
        course_code=body.courseCode,
        semester=body.semester,
        title=body.title,
        instructor_email=body.instructorEmail,
    )
    response.headers["Location"] = f"/api/v1/offerings/{view['id']}"
    set_etag(response, view["version"])
    return view


@router.get(
    "/offerings/{offeringId}",
    operation_id="getCourse",
    response_model=Offering,
    summary="Class page header; class members and admins only (others get 404).",
)
def get_course(
    offering_id: OfferingId, actor: ActorDep, response: Response, service: CourseServiceDep
):
    view = service.get_offering(actor=actor, offering_id=offering_id)
    set_etag(response, view["version"])
    return view


@router.get(
    "/offerings/{offeringId}/approved-students",
    operation_id="listApprovedStudents",
    response_model=StudentList,
    summary="Professor's waiting list: approved for the course, not in any of its classes yet.",
)
def list_approved_students(offering_id: OfferingId, actor: ActorDep, service: CourseServiceDep):
    return service.list_approved_students(actor=actor, offering_id=offering_id)


@router.patch("/offerings/{offeringId}", operation_id="updateCourse", status_code=501)
def update_course(offeringId: int = Path(ge=1, le=2147483647)):
    return CourseService().update_course(offering_id=offeringId)


@router.post("/offerings/{offeringId}/restore", operation_id="restoreOffering", status_code=501)
def restore_offering(offeringId: int = Path(ge=1, le=2147483647)):
    return CourseService().restore_offering(offering_id=offeringId)


@router.get(
    "/courses",
    operation_id="listCatalogCourses",
    response_model=CatalogCoursePage,
    summary="Search the course catalog by code prefix (CS10) or by name (programming).",
    responses={400: {"description": "INVALID_SEARCH"}},
)
def list_catalog_courses(
    actor: ActorDep,
    service: CourseServiceDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    pageSize: Annotated[int, Query(ge=1, le=100)] = 25,
):
    return service.search_courses(actor=actor, query=q, page=page, page_size=pageSize)
