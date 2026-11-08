"""Accounts, sessions, passwords and operational administration (FR-01, FR-02, FR-16/17)."""

from dataclasses import dataclass
from typing import Any

from app.core.config import Settings
from app.core.errors import (
    ApiError,
    FeatureNotImplemented,
    conflict,
    forbidden,
    not_found,
    unauthenticated,
    version_conflict,
)
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    csrf_token_for,
    hash_password,
    new_session_token,
    temporary_password,
    token_hash,
    verify_password,
)
from app.domain.context import Actor, SessionContext
from app.infrastructure.credential_outbox import CredentialOutbox
from app.infrastructure.db.repositories.audit_repository import AuditRepository
from app.infrastructure.db.repositories.identity_repository import (
    IdentityRepository,
    account_view,
    user_from_row,
)
from app.infrastructure.db.sql import Sql, is_unique_violation

MIN_PASSWORD_LENGTH = 12


@dataclass(frozen=True)
class IssuedSession:
    token: str
    view: dict[str, Any]


def normalize_email(email: str) -> str:
    return email.strip().lower()


class AuthService:
    def __init__(self, database, settings: Settings):
        self.database = database
        self.settings = settings
        self.outbox = CredentialOutbox(settings.credential_outbox_dir)

    # ------------------------------------------------------------ sessions
    def login(self, *, email: str, password: str) -> IssuedSession:
        with self.database.transaction() as connection:
            repo = IdentityRepository(Sql(connection))
            account = repo.find_by_email(normalize_email(email))
            user = user_from_row(account) if account else None
            # Always run one hash verification so unknown emails cost the same time.
            stored = user.password_hash if user else DUMMY_PASSWORD_HASH
            valid = verify_password(password, stored)
            if not user or not valid or not user.is_active():
                raise ApiError(401, "INVALID_CREDENTIALS", "Email or password is incorrect.")
            restricted = user.must_change_password
            token = new_session_token()
            session = repo.insert_session(
                user_id=account["user_id"],
                token_hash=token_hash(token),
                ttl_hours=self.settings.session_ttl_hours,
                restricted=restricted,
            )
        view = {
            "account": account_view(account)["account"],
            "csrfToken": csrf_token_for(token),
            "absoluteExpiresAt": session["expires_at"],
            "restricted": restricted,
        }
        return IssuedSession(token=token, view=view)

    def resolve_session(self, token: str | None) -> SessionContext:
        if not token or len(token) > 256:
            raise unauthenticated()
        with self.database.read_connection() as connection:
            row = IdentityRepository(Sql(connection)).find_live_session(token_hash(token))
        if row is None:
            raise unauthenticated()
        actor = Actor(user_id=row["user_id"], role=row["role"], restricted=bool(row["restricted"]))
        return SessionContext(
            actor=actor, session_id=row["session_id"], token=token, expires_at=row["expires_at"]
        )

    def logout(self, *, session: SessionContext) -> None:
        with self.database.transaction() as connection:
            IdentityRepository(Sql(connection)).revoke_session(session.session_id)

    def revoke_all_sessions(self, *, user_id: int) -> int:
        with self.database.transaction() as connection:
            return IdentityRepository(Sql(connection)).revoke_all_sessions(user_id)

    # ------------------------------------------------------------ self service
    def get_me(self, *, actor: Actor) -> dict[str, Any]:
        with self.database.read_connection() as connection:
            account = IdentityRepository(Sql(connection)).get_account(actor.user_id)
        if account is None:
            raise unauthenticated()
        return account_view(account)

    def update_me(self, *, actor: Actor, display_name: str, expected_version: int) -> dict:
        name = display_name.strip()
        if not name:
            raise ApiError(400, "INVALID_REQUEST", "Display name must not be blank.")
        with self.database.transaction() as connection:
            repo = IdentityRepository(Sql(connection))
            account = repo.get_account(actor.user_id, lock=True)
            if account is None:
                raise unauthenticated()
            if account["version"] != expected_version:
                raise version_conflict(account["version"])
            repo.update_display_name(actor.user_id, name)
            return account_view(repo.get_account(actor.user_id))

    def change_password(self, *, actor: Actor, current_password: str, new_password: str) -> dict:
        _check_new_password(new_password)
        with self.database.transaction() as connection:
            repo = IdentityRepository(Sql(connection))
            account = repo.get_account(actor.user_id, lock=True)
            if account is None:
                raise unauthenticated()
            if not verify_password(current_password, account["password_hash"]):
                raise ApiError(400, "INVALID_CURRENT_PASSWORD", "Current password is incorrect.")
            if verify_password(new_password, account["password_hash"]):
                raise ApiError(
                    400, "PASSWORD_REUSED", "New password must differ from the current one."
                )
            repo.update_password(actor.user_id, hash_password(new_password), must_change=False)
            # Revokes every session, including the one making this request.
            repo.revoke_all_sessions(actor.user_id)
        return {"status": "COMPLETED", "resourceId": actor.user_id}

    # ------------------------------------------------------------ administration
    def bootstrap_admin(self, *, email: str, display_name: str, password: str) -> int:
        """Create the very first administrator (CLI only). Refuses when an admin exists."""
        _check_new_password(password)
        with self.database.transaction() as connection:
            repo = IdentityRepository(Sql(connection))
            if repo.count_admins() > 0:
                raise conflict("ADMIN_EXISTS", "An administrator already exists.")
            user_id = repo.insert_user(
                email=normalize_email(email),
                full_name=display_name.strip(),
                password_hash=hash_password(password),
                role="ADMIN",
                must_change_pwd=False,
                created_by=None,
            )
            repo.insert_admin(user_id)
            return user_id

    def create_account_with_password(
        self,
        *,
        email: str,
        display_name: str,
        role: str,
        password: str,
        can_create_course: bool = False,
    ) -> int:
        """Operator/CLI account creation with a chosen password (no temporary password).

        Recorded in the audit log as created by the first administrator.
        """
        _check_new_password(password)
        name = display_name.strip()
        if not name:
            raise ApiError(400, "INVALID_REQUEST", "Display name must not be blank.")
        if can_create_course and role != "INSTRUCTOR":
            raise ApiError(
                400, "INVALID_REQUEST", "Only instructors can be allowed to create courses."
            )
        try:
            with self.database.transaction() as connection:
                sql = Sql(connection)
                repo = IdentityRepository(sql)
                admin_id = repo.first_admin_id()
                if admin_id is None:
                    raise conflict("NO_ADMIN", "Create an administrator first.")
                user_id = repo.insert_user(
                    email=normalize_email(email),
                    full_name=name,
                    password_hash=hash_password(password),
                    role=role,
                    must_change_pwd=False,
                    created_by=admin_id,
                )
                if role == "STUDENT":
                    repo.insert_student(user_id)
                elif role == "INSTRUCTOR":
                    repo.insert_instructor(user_id, can_create_course)
                else:
                    repo.insert_admin(user_id)
                AuditRepository(sql).record(
                    actor_id=admin_id,
                    action="ACCOUNT_CREATED",
                    target_type="ACCOUNT",
                    target_id=user_id,
                    details={"role": role, "canCreateCourse": can_create_course, "via": "cli"},
                )
                return user_id
        except Exception as error:
            if is_unique_violation(error):
                raise conflict(
                    "EMAIL_TAKEN", "An account with this email already exists."
                ) from None
            raise

    def sign_up_student(self, *, email: str, display_name: str, password: str) -> dict[str, Any]:
        """Public self sign-up (team MVP addition). Students only; usable at once.

        created_by stays NULL: the account was not provisioned by an administrator.
        Instructors and admins are still created by an administrator.
        """
        _check_new_password(password)
        name = display_name.strip()
        if not name:
            raise ApiError(400, "INVALID_REQUEST", "Display name must not be blank.")
        try:
            with self.database.transaction() as connection:
                sql = Sql(connection)
                repo = IdentityRepository(sql)
                user_id = repo.insert_user(
                    email=normalize_email(email),
                    full_name=name,
                    password_hash=hash_password(password),
                    role="STUDENT",
                    must_change_pwd=False,
                    created_by=None,
                )
                repo.insert_student(user_id)
                AuditRepository(sql).record(
                    actor_id=user_id,
                    action="ACCOUNT_SIGNED_UP",
                    target_type="ACCOUNT",
                    target_id=user_id,
                    details={"role": "STUDENT"},
                )
                account = repo.get_account(user_id)
        except Exception as error:
            if is_unique_violation(error):
                raise conflict(
                    "EMAIL_TAKEN", "An account with this email already exists."
                ) from None
            raise
        return account_view(account)

    def create_account(
        self, *, actor: Actor, email: str, display_name: str, role: str, can_create_course: bool
    ) -> dict[str, Any]:
        _require_admin(actor)
        name = display_name.strip()
        if not name:
            raise ApiError(400, "INVALID_REQUEST", "Display name must not be blank.")
        if can_create_course and role != "INSTRUCTOR":
            raise ApiError(
                400, "INVALID_REQUEST", "Only instructors can be allowed to create courses."
            )
        password = temporary_password()
        normalized = normalize_email(email)
        try:
            with self.database.transaction() as connection:
                sql = Sql(connection)
                repo = IdentityRepository(sql)
                user_id = repo.insert_user(
                    email=normalized,
                    full_name=name,
                    password_hash=hash_password(password),
                    role=role,
                    must_change_pwd=True,
                    created_by=actor.user_id,
                )
                if role == "STUDENT":
                    repo.insert_student(user_id)
                elif role == "INSTRUCTOR":
                    repo.insert_instructor(user_id, can_create_course)
                else:
                    repo.insert_admin(user_id)
                AuditRepository(sql).record(
                    actor_id=actor.user_id,
                    action="ACCOUNT_CREATED",
                    target_type="ACCOUNT",
                    target_id=user_id,
                    details={"role": role, "canCreateCourse": can_create_course},
                )
                view = account_view(repo.get_account(user_id))
                # Inside the transaction: if delivery fails, the account is not created.
                self.outbox.deliver(
                    account_id=user_id, email=normalized, temporary_password=password
                )
        except Exception as error:
            if is_unique_violation(error):
                raise conflict(
                    "EMAIL_TAKEN", "An account with this email already exists."
                ) from None
            raise
        return view

    def update_account(
        self,
        *,
        actor: Actor,
        account_id: int,
        expected_version: int,
        reason: str,
        status: str | None,
        can_create_course: bool | None,
    ) -> dict[str, Any]:
        _require_admin(actor)
        if status is None and can_create_course is None:
            raise ApiError(400, "INVALID_REQUEST", "Nothing to update.")
        with self.database.transaction() as connection:
            sql = Sql(connection)
            repo = IdentityRepository(sql)
            account = repo.get_account(account_id, lock=True)
            if account is None:
                raise not_found("Account")
            if account["version"] != expected_version:
                raise version_conflict(account["version"])
            changes: dict[str, Any] = {}
            if status is not None and status != account["status"]:
                if account_id == actor.user_id:
                    raise conflict("SELF_LOCK", "You cannot lock your own account.")
                if status == "LOCKED" and repo.count_open_leaderships(account_id) > 0:
                    raise conflict(
                        "LEAD_TRANSFER_REQUIRED",
                        "Transfer this instructor's lead role in draft/open courses before locking.",
                    )
                repo.update_status(account_id, status)
                if status == "LOCKED":
                    repo.revoke_all_sessions(account_id)
                changes["status"] = status
            if can_create_course is not None and can_create_course != bool(
                account["can_create_course"]
            ):
                if account["role"] != "INSTRUCTOR":
                    raise ApiError(
                        400, "INVALID_REQUEST", "Only instructors can be allowed to create courses."
                    )
                repo.update_can_create_course(account_id, can_create_course)
                changes["canCreateCourse"] = can_create_course
            if changes:
                AuditRepository(sql).record(
                    actor_id=actor.user_id,
                    action="ACCOUNT_UPDATED",
                    target_type="ACCOUNT",
                    target_id=account_id,
                    reason=reason,
                    details=changes,
                )
            return account_view(repo.get_account(account_id))

    def reset_password(self, *, actor: Actor, account_id: int, reason: str) -> dict:
        _require_admin(actor)
        password = temporary_password()
        with self.database.transaction() as connection:
            sql = Sql(connection)
            repo = IdentityRepository(sql)
            account = repo.get_account(account_id, lock=True)
            if account is None:
                raise not_found("Account")
            repo.update_password(account_id, hash_password(password), must_change=True)
            repo.revoke_all_sessions(account_id)
            AuditRepository(sql).record(
                actor_id=actor.user_id,
                action="PASSWORD_RESET",
                target_type="ACCOUNT",
                target_id=account_id,
                reason=reason,
            )
            self.outbox.deliver(
                account_id=account_id, email=account["email"], temporary_password=password
            )
        return {"status": "COMPLETED", "resourceId": account_id}

    def admin_list_accounts(
        self,
        *,
        actor: Actor,
        page: int,
        page_size: int,
        q: str | None,
        status: str | None,
        can_create_course: bool | None,
    ) -> dict[str, Any]:
        _require_admin(actor)
        with self.database.read_connection() as connection:
            rows, total = IdentityRepository(Sql(connection)).list_accounts(
                q=q,
                status=status,
                can_create_course=can_create_course,
                offset=(page - 1) * page_size,
                limit=page_size,
            )
        return {
            "items": [account_view(row) for row in rows],
            "page": page,
            "pageSize": page_size,
            "totalItems": total,
            "totalPages": (total + page_size - 1) // page_size,
        }

    # Sprint 2 (not part of MVP)
    def admin_list_audit_entries(self, **kwargs: object):
        raise FeatureNotImplemented("AuthService.admin_list_audit_entries")

    def admin_list_courses(self, **kwargs: object):
        raise FeatureNotImplemented("AuthService.admin_list_courses")


def _require_admin(actor: Actor) -> None:
    if actor.role != "ADMIN":
        raise forbidden()


def _check_new_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ApiError(
            400, "WEAK_PASSWORD", f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
        )
