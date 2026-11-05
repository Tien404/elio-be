from collections.abc import Iterator
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Any, BinaryIO, Protocol

from app.domain.context import Actor


class DbConnection(Protocol):
    def cursor(self) -> Any: ...


class IRepository(Protocol):
    def transaction(self) -> AbstractContextManager[DbConnection]: ...


class IFileStorage(Protocol):
    def save(self, stream: BinaryIO) -> str: ...
    def read(self, key: str) -> Iterator[bytes]: ...


class IAccessControl(Protocol):
    def require(self, actor: Actor, action: str, resource_id: int) -> None: ...


class IAudit(Protocol):
    def record(self, actor: Actor, action: str, target_id: int) -> None: ...


class INotification(Protocol):
    def notify_course(self, offering_id: int, event_key: str) -> None: ...


class IClock(Protocol):
    def now(self) -> datetime: ...


class IQuizFinalizer(Protocol):
    def finalize_expired_attempts(self) -> None: ...
