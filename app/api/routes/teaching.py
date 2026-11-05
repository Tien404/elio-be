from fastapi import APIRouter, Path

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
    "/offerings/{offeringId}/teaching-team", operation_id="getTeachingTeam", status_code=501
)
def get_teaching_team(offeringId: int = Path(ge=1, le=2147483647)):
    return CourseService().get_teaching_team(offering_id=offeringId)


@router.post(
    "/offerings/{offeringId}/teaching-team", operation_id="addCoInstructor", status_code=501
)
def add_co_instructor(offeringId: int = Path(ge=1, le=2147483647)):
    return CourseService().add_co_instructor(offering_id=offeringId)


@router.post("/offerings/{offeringId}/lead-transfer", operation_id="transferLead", status_code=501)
def transfer_lead(offeringId: int = Path(ge=1, le=2147483647)):
    return CourseService().transfer_leadership(offering_id=offeringId)
