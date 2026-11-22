from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import AwareDatetime

from app.api.dependencies import ActorDep, CourseServiceDep, DatabaseDep
from app.api.schemas.personal import CalendarPage, PersonalDashboard, ProgressView
from app.services.personal_service import PersonalService

router = APIRouter(tags=["projections"], responses={400: {"description": "Invalid request"}})


@router.get("/dashboard", operation_id="getDashboard", response_model=PersonalDashboard)
def get_dashboard(actor: ActorDep, service: CourseServiceDep, database: DatabaseDep):
    return PersonalService(database).dashboard(actor, service.get_dashboard(actor=actor))


@router.get(
    "/me/calendar",
    operation_id="getMyCalendar",
    response_model=CalendarPage,
    summary="Assignments due and quizzes open in my classes (default: the next 30 days).",
)
def get_my_calendar(
    actor: ActorDep,
    database: DatabaseDep,
    offeringId: int | None = None,
    kind: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    pageSize: Annotated[int, Query(ge=1, le=100)] = 25,
    start: Annotated[AwareDatetime | None, Query(alias="from")] = None,
    end: Annotated[AwareDatetime | None, Query(alias="to")] = None,
):
    return PersonalService(database).calendar(
        actor=actor,
        offering_id=offeringId,
        kind=kind,
        start=start,
        end=end,
        page=page,
        page_size=pageSize,
    )


@router.get(
    "/me/progress",
    operation_id="getMyProgress",
    response_model=ProgressView,
    summary="Student: my progress in each class (x of y done, overall %).",
)
def get_my_progress(
    actor: ActorDep,
    database: DatabaseDep,
    page: Annotated[int, Query(ge=1)] = 1,
    pageSize: Annotated[int, Query(ge=1, le=100)] = 25,
):
    return PersonalService(database).progress(actor=actor, page=page, page_size=pageSize)
