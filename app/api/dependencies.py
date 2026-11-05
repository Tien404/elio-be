from fastapi import Request

from app.core.errors import PolicyNotImplemented
from app.domain.context import Actor


def current_actor(request: Request) -> Actor:
    raise PolicyNotImplemented("AuthService.resolve_session")


def require_csrf(request: Request) -> None:
    raise PolicyNotImplemented("Session-bound CSRF validation")
