from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import AwareDatetime

from app.api.dependencies import ActorDep, CourseServiceDep
from app.api.schemas.reports import Calendar, MyProgress
from app.api.schemas.views import Dashboard

router = APIRouter(tags=["projections"], responses={400: {"description": "Invalid request"}})


@router.get("/dashboard", operation_id="getDashboard", response_model=Dashboard)
def get_dashboard(actor: ActorDep, service: CourseServiceDep):
    return service.get_dashboard(actor=actor)


@router.get(
    "/me/calendar",
    operation_id="getMyCalendar",
    response_model=Calendar,
    summary="Assignments due and quizzes open in my classes (default: the next 30 days).",
)
def get_my_calendar(
    actor: ActorDep,
    service: CourseServiceDep,
    start: Annotated[AwareDatetime | None, Query(alias="from")] = None,
    end: Annotated[AwareDatetime | None, Query(alias="to")] = None,
):
    return service.get_my_calendar(actor=actor, start=start, end=end)


@router.get(
    "/me/progress",
    operation_id="getMyProgress",
    response_model=MyProgress,
    summary="Student: my progress in each class (x of y done, overall %).",
)
def get_my_progress(actor: ActorDep, service: CourseServiceDep):
    return service.get_my_progress(actor=actor)
