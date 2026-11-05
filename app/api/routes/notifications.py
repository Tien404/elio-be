from fastapi import APIRouter, Path

from app.services.notification_service import NotificationService

router = APIRouter(tags=["notifications"], responses={400: {"description": "Invalid request"}})


@router.get("/me/notifications", operation_id="listMyNotifications", status_code=501)
def list_my_notifications():
    return NotificationService().list_personal()


@router.put(
    "/me/notifications/{notificationId}/read", operation_id="markNotificationRead", status_code=501
)
def mark_notification_read(notificationId: int = Path(ge=1, le=2147483647)):
    return NotificationService().mark_notification_read(notification_id=notificationId)
