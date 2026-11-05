from app.core.errors import FeatureNotImplemented


class NotificationService:
    def list_personal(self, **kwargs: object):
        raise FeatureNotImplemented("NotificationService.list_personal")

    def mark_notification_read(self, **kwargs: object):
        raise FeatureNotImplemented("NotificationService.mark_notification_read")

    def notify_course(self, **kwargs: object):
        raise FeatureNotImplemented("NotificationService.notify_course")

    def retry_pending(self, **kwargs: object):
        raise FeatureNotImplemented("NotificationService.retry_pending")

    def get_notifications(self, **kwargs: object):
        raise FeatureNotImplemented("NotificationService.get_notifications")
