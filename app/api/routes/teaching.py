from typing import Annotated

from fastapi import APIRouter, Path, Query

from app.api.dependencies import ActorDep, CourseServiceDep
from app.api.schemas.offerings import MembershipPage
from app.services.course_service import CourseService

router = APIRouter(tags=["teaching"], responses={400: {"description": "Invalid request"}})


@router.patch(
    "/offerings/{offeringId}/memberships/{membershipId}",
    operation_id="removeInstructorMembership",
    status_code=501,
)
def remove_instructor_membership(
    offeringId: int = Path(ge=1, le=2147483647), membershipId: int = Path(ge=1, le=2147483647)
):
    return CourseService().remove_instructor_membership(
        offering_id=offeringId, membership_id=membershipId
    )


@router.get(
    "/offerings/{offeringId}/teaching-team",
    operation_id="getTeachingTeam",
    response_model=MembershipPage,
)
def get_teaching_team(
    offeringId: Annotated[int, Path(ge=1, le=2147483647)],
    actor: ActorDep,
    service: CourseServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    pageSize: Annotated[int, Query(ge=1, le=100)] = 25,
):
    return service.get_teaching_team(
        actor=actor, offering_id=offeringId, page=page, page_size=pageSize
    )


@router.post(
    "/offerings/{offeringId}/teaching-team", operation_id="addCoInstructor", status_code=501
)
def add_co_instructor(offeringId: int = Path(ge=1, le=2147483647)):
    return CourseService().add_co_instructor(offering_id=offeringId)


@router.post("/offerings/{offeringId}/lead-transfer", operation_id="transferLead", status_code=501)
def transfer_lead(offeringId: int = Path(ge=1, le=2147483647)):
    return CourseService().transfer_leadership(offering_id=offeringId)
