from app.core.errors import FeatureNotImplemented


class AuthService:
    def admin_create_account(self, **kwargs: object):
        raise FeatureNotImplemented("AuthService.admin_create_account")

    def admin_list_accounts(self, **kwargs: object):
        raise FeatureNotImplemented("AuthService.admin_list_accounts")

    def admin_list_audit_entries(self, **kwargs: object):
        raise FeatureNotImplemented("AuthService.admin_list_audit_entries")

    def admin_list_courses(self, **kwargs: object):
        raise FeatureNotImplemented("AuthService.admin_list_courses")

    def admin_reset_password(self, **kwargs: object):
        raise FeatureNotImplemented("AuthService.admin_reset_password")

    def admin_update_account(self, **kwargs: object):
        raise FeatureNotImplemented("AuthService.admin_update_account")

    def change_password(self, **kwargs: object):
        raise FeatureNotImplemented("AuthService.change_password")

    def get_me(self, **kwargs: object):
        raise FeatureNotImplemented("AuthService.get_me")

    def login(self, **kwargs: object):
        raise FeatureNotImplemented("AuthService.login")

    def logout(self, **kwargs: object):
        raise FeatureNotImplemented("AuthService.logout")

    def update_me(self, **kwargs: object):
        raise FeatureNotImplemented("AuthService.update_me")

    def revoke_all_sessions(self, **kwargs: object):
        raise FeatureNotImplemented("AuthService.revoke_all_sessions")
