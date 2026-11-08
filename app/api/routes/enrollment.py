from typing import Annotated

from fastapi import APIRouter, Path, Query, Response

from app.api.dependencies import ActorDep, CourseServiceDep, MutationActorDep
from app.api.schemas.catalog import Registration
from app.api.schemas.offerings import EnrollStudentRequest, Membership, MembershipPage

router = APIRouter(tags=["enrollment"], responses={400: {"description": "Invalid request"}})

CourseId = Annotated[int, Path(alias="courseId", ge=1, le=2147483647)]
OfferingId = Annotated[int, Path(alias="offeringId", ge=1, le=2147483647)]


@router.post(
    "/courses/{courseId}/registrations",
    operation_id="requestEnrollment",
    status_code=201,
    response_model=Registration,
    summary="Student asks to take a catalog course; an admin approves or rejects it.",
    responses={
        403: {"description": "FORBIDDEN (students only)"},
        404: {"description": "Course not found"},
        409: {"description": "ALREADY_REQUESTED"},
    },
)
def request_enrollment(course_id: CourseId, actor: MutationActorDep, service: CourseServiceDep):
    return service.request_enrollment(actor=actor, course_id=course_id)


@router.post(
    "/offerings/{offeringId}/enrollments",
    operation_id="joinCourse",
    status_code=201,
    response_model=Membership,
    summary="The class professor adds an approved student by email (contract gap API-G01).",
    responses={
        403: {"description": "FORBIDDEN (class professor only)"},
        404: {"description": "Class not found"},
        409: {"description": "NOT_APPROVED / ALREADY_ENROLLED / CLASS_NOT_OPEN"},
        422: {"description": "STUDENT_NOT_FOUND"},
    },
)
def join_course(
    offering_id: OfferingId,
    body: EnrollStudentRequest,
    actor: MutationActorDep,
    response: Response,
    service: CourseServiceDep,
):
    view = service.enroll_student(actor=actor, offering_id=offering_id, student_email=body.email)
    response.headers["Location"] = f"/api/v1/offerings/{offering_id}/memberships"
    return view


@router.get(
    "/offerings/{offeringId}/memberships",
    operation_id="listMemberships",
    response_model=MembershipPage,
    summary="Class roster (professor first); class members and admins only.",
)
def list_memberships(
    offering_id: OfferingId,
    actor: ActorDep,
    service: CourseServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    pageSize: Annotated[int, Query(ge=1, le=100)] = 25,
):
    return service.get_roster(actor=actor, offering_id=offering_id, page=page, page_size=pageSize)
