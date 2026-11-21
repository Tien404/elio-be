from typing import Annotated

from fastapi import APIRouter, Path, Query, Response

from app.api.dependencies import ActorDep, MutationActorDep, NotificationServiceDep
from app.api.schemas.reports import NotificationPage

router = APIRouter(tags=["notifications"], responses={400: {"description": "Invalid request"}})


@router.get(
    "/me/notifications",
    operation_id="listMyNotifications",
    response_model=NotificationPage,
    summary="My inbox, newest first, with the unread count.",
)
def list_my_notifications(
    actor: ActorDep,
    service: NotificationServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    pageSize: Annotated[int, Query(ge=1, le=100)] = 25,
    unreadOnly: bool = False,
):
    return service.list_personal(actor=actor, page=page, page_size=pageSize, unread_only=unreadOnly)


@router.put(
    "/me/notifications/{notificationId}/read",
    operation_id="markNotificationRead",
    status_code=204,
    summary="Mark one of my notifications as read.",
)
def mark_notification_read(
    notificationId: Annotated[int, Path(ge=1, le=2147483647)],
    actor: MutationActorDep,
    service: NotificationServiceDep,
):
    service.mark_notification_read(actor=actor, notification_id=notificationId)
    return Response(status_code=204)
