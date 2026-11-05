from app.core.errors import FeatureNotImplemented


class SubmissionService:
    def confirm(self, **kwargs: object):
        raise FeatureNotImplemented("SubmissionService.confirm")

    def create_group(self, **kwargs: object):
        raise FeatureNotImplemented("SubmissionService.create_group")

    def get_assignment(self, **kwargs: object):
        raise FeatureNotImplemented("SubmissionService.get_assignment")

    def get_group(self, **kwargs: object):
        raise FeatureNotImplemented("SubmissionService.get_group")

    def get_submission(self, **kwargs: object):
        raise FeatureNotImplemented("SubmissionService.get_submission")

    def get_submission_receipt(self, **kwargs: object):
        raise FeatureNotImplemented("SubmissionService.get_submission_receipt")

    def list_assignments(self, **kwargs: object):
        raise FeatureNotImplemented("SubmissionService.list_assignments")

    def list_groups(self, **kwargs: object):
        raise FeatureNotImplemented("SubmissionService.list_groups")

    def list_submissions(self, **kwargs: object):
        raise FeatureNotImplemented("SubmissionService.list_submissions")

    def save_assignment(self, **kwargs: object):
        raise FeatureNotImplemented("SubmissionService.save_assignment")

    def update_assignment(self, **kwargs: object):
        raise FeatureNotImplemented("SubmissionService.update_assignment")

    def update_group(self, **kwargs: object):
        raise FeatureNotImplemented("SubmissionService.update_group")

    def upload_files(self, **kwargs: object):
        raise FeatureNotImplemented("SubmissionService.upload_files")
