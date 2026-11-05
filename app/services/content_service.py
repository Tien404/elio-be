from app.core.errors import FeatureNotImplemented


class ContentService:
    def create_announcement(self, **kwargs: object):
        raise FeatureNotImplemented("ContentService.create_announcement")

    def create_topic(self, **kwargs: object):
        raise FeatureNotImplemented("ContentService.create_topic")

    def download_file(self, **kwargs: object):
        raise FeatureNotImplemented("ContentService.download_file")

    def list_announcements(self, **kwargs: object):
        raise FeatureNotImplemented("ContentService.list_announcements")

    def list_resources(self, **kwargs: object):
        raise FeatureNotImplemented("ContentService.list_resources")

    def list_topics(self, **kwargs: object):
        raise FeatureNotImplemented("ContentService.list_topics")

    def prepare_file(self, **kwargs: object):
        raise FeatureNotImplemented("ContentService.prepare_file")

    def read_material(self, **kwargs: object):
        raise FeatureNotImplemented("ContentService.read_material")

    def save_material(self, **kwargs: object):
        raise FeatureNotImplemented("ContentService.save_material")

    def update_resource(self, **kwargs: object):
        raise FeatureNotImplemented("ContentService.update_resource")

    def update_topic(self, **kwargs: object):
        raise FeatureNotImplemented("ContentService.update_topic")

    def publish_material(self, **kwargs: object):
        raise FeatureNotImplemented("ContentService.publish_material")

    def download_material(self, **kwargs: object):
        raise FeatureNotImplemented("ContentService.download_material")
