from typing import Annotated

from fastapi import APIRouter, Path, Query

from app.api.dependencies import ActorDep, CourseServiceDep, DatabaseDep, MutationActorDep
from app.api.schemas.offerings import (
    AddCoInstructorRequest,
    Membership,
    MembershipPage,
    RemoveMembershipRequest,
    TransferLeadRequest,
)

router = APIRouter(tags=["teaching"], responses={400: {"description": "Invalid request"}})


OfferingId = Annotated[int, Path(alias="offeringId", ge=1, le=2147483647)]


@router.patch(
    "/offerings/{offeringId}/memberships/{membershipId}",
    operation_id="removeInstructorMembership",
    response_model=Membership,
    summary="Remove a co-instructor (lead or admin), or leave the team yourself.",
    responses={409: {"description": "LEAD_CANNOT_BE_REMOVED or NOT_A_CO_INSTRUCTOR"}},
)
def remove_instructor_membership(
    offering_id: OfferingId,
    membership_id: Annotated[int, Path(alias="membershipId", ge=1, le=2147483647)],
    body: RemoveMembershipRequest,
    actor: MutationActorDep,
    service: CourseServiceDep,
):
    return service.remove_instructor_membership(
        actor=actor, offering_id=offering_id, membership_id=membership_id, reason=body.reason
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
    "/offerings/{offeringId}/teaching-team",
    operation_id="addCoInstructor",
    status_code=201,
    response_model=Membership,
    summary="Lead (or admin) adds an instructor to the teaching team by email.",
    responses={
        409: {"description": "ALREADY_MEMBER"},
        422: {"description": "INSTRUCTOR_NOT_FOUND"},
    },
)
def add_co_instructor(
    offering_id: OfferingId,
    body: AddCoInstructorRequest,
    actor: MutationActorDep,
    service: CourseServiceDep,
):
    return service.add_co_instructor(
        actor=actor,
        offering_id=offering_id,
        email=body.email,
        account_id=body.accountId,
        reason=body.reason,
    )


@router.post(
    "/offerings/{offeringId}/lead-transfer",
    operation_id="transferLead",
    response_model=Membership,
    summary="Lead (or admin) hands the class to a co-instructor; the old lead stays as co.",
    responses={422: {"description": "NOT_A_CO_INSTRUCTOR"}},
)
def transfer_lead(
    offering_id: OfferingId,
    body: TransferLeadRequest,
    actor: MutationActorDep,
    service: CourseServiceDep,
):
    return service.transfer_leadership(
        actor=actor, offering_id=offering_id, membership_id=body.membershipId, reason=body.reason
    )


@router.get(
    "/offerings/{offeringId}/teaching-team/candidates", operation_id="listInstructorCandidates"
)
def instructor_candidates(
    offering_id: OfferingId,
    actor: ActorDep,
    service: CourseServiceDep,
    q: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    pageSize: Annotated[int, Query(ge=1, le=100)] = 25,
):
    return service.list_instructor_candidates(
        actor=actor, offering_id=offering_id, q=q, page=page, page_size=pageSize
    )


@router.get("/offerings/{offeringId}/audit-entries", operation_id="listOfferingAuditEntries")
def offering_audit(
    offering_id: OfferingId,
    actor: ActorDep,
    database: DatabaseDep,
    page: Annotated[int, Query(ge=1)] = 1,
    pageSize: Annotated[int, Query(ge=1, le=100)] = 25,
):
    from app.infrastructure.db.repositories.course_repository import CourseRepository
    from app.infrastructure.db.repositories.report_repository import ReportRepository
    from app.infrastructure.db.sql import Sql
    from app.services.course_service import CourseService

    with database.transaction() as connection:
        sql = Sql(connection)
        CourseService._require_lead(CourseRepository(sql), actor, offering_id, allow_admin=True)
        rows, total = ReportRepository(sql).audit_entries(
            actor_id=None,
            action=None,
            target_type=None,
            offering_id=offering_id,
            offset=(page - 1) * pageSize,
            limit=pageSize,
        )
        return {
            "items": [
                {
                    "id": r["audit_id"],
                    "actorId": r["actor_id"],
                    "action": r["action_type"],
                    "targetType": r["target_type"],
                    "targetId": r["target_id"],
                    "createdAt": r["created_at"],
                    "reason": r["reason"],
                }
                for r in rows
            ],
            "page": page,
            "pageSize": pageSize,
            "totalItems": total,
            "totalPages": (total + pageSize - 1) // pageSize,
        }
