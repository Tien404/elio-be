from fastapi import APIRouter

from app.api.dependencies import ActorDep, CourseServiceDep
from app.api.schemas.views import Dashboard
from app.services.course_service import CourseService

router = APIRouter(tags=["projections"], responses={400: {"description": "Invalid request"}})


@router.get("/dashboard", operation_id="getDashboard", response_model=Dashboard)
def get_dashboard(actor: ActorDep, service: CourseServiceDep):
    return service.get_dashboard(actor=actor)


@router.get("/me/calendar", operation_id="getMyCalendar", status_code=501)
def get_my_calendar():
    return CourseService().get_my_calendar()


@router.get("/me/progress", operation_id="getMyProgress", status_code=501)
def get_my_progress():
    return CourseService().get_my_progress()
