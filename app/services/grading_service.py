from app.core.errors import FeatureNotImplemented


class GradingService:
    def confirm_missing_work(self, **kwargs: object):
        raise FeatureNotImplemented("GradingService.confirm_missing_work")

    def export_gradebook_csv(self, **kwargs: object):
        raise FeatureNotImplemented("GradingService.export_gradebook_csv")

    def get_grade_record(self, **kwargs: object):
        raise FeatureNotImplemented("GradingService.get_grade_record")

    def get_gradebook(self, **kwargs: object):
        raise FeatureNotImplemented("GradingService.get_gradebook")

    def get_my_grades(self, **kwargs: object):
        raise FeatureNotImplemented("GradingService.get_my_grades")

    def list_assignment_grade_records(self, **kwargs: object):
        raise FeatureNotImplemented("GradingService.list_assignment_grade_records")

    def publish(self, **kwargs: object):
        raise FeatureNotImplemented("GradingService.publish")

    def revise(self, **kwargs: object):
        raise FeatureNotImplemented("GradingService.revise")

    def save_draft(self, **kwargs: object):
        raise FeatureNotImplemented("GradingService.save_draft")
