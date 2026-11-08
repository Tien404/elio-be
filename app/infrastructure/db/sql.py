"""Thin helpers over a pyodbc connection: explicit row mapping, ? parameters, cursor always closed.

Repositories receive a `Sql` bound to the use case's single transaction connection and
never commit. Diagnostics from the driver never leave this layer except as constraint names
used internally to translate integrity errors into business errors.
"""

import re
from typing import Any

_CONSTRAINT = re.compile(r"constraint '([^']+)'|unique index '([^']+)'", re.IGNORECASE)
# 2627 unique constraint, 2601 unique index, 547 FK/CHECK
_UNIQUE_CODES = ("(2627)", "(2601)")


class Sql:
    def __init__(self, connection: Any):
        self.connection = connection

    def _run(self, statement: str, params: tuple):
        cursor = self.connection.cursor()
        try:
            cursor.execute(statement, *params)
            return cursor
        except BaseException:
            cursor.close()
            raise

    def all(self, statement: str, *params: Any) -> list[dict[str, Any]]:
        cursor = self._run(statement, params)
        try:
            names = [column[0] for column in cursor.description]
            return [dict(zip(names, row)) for row in cursor.fetchall()]
        finally:
            cursor.close()

    def one(self, statement: str, *params: Any) -> dict[str, Any] | None:
        cursor = self._run(statement, params)
        try:
            row = cursor.fetchone()
            if row is None:
                return None
            names = [column[0] for column in cursor.description]
            return dict(zip(names, row))
        finally:
            cursor.close()

    def scalar(self, statement: str, *params: Any) -> Any:
        cursor = self._run(statement, params)
        try:
            row = cursor.fetchone()
            return None if row is None else row[0]
        finally:
            cursor.close()

    def execute(self, statement: str, *params: Any) -> int:
        cursor = self._run(statement, params)
        try:
            return cursor.rowcount
        finally:
            cursor.close()


def violated_constraint(error: BaseException) -> str | None:
    """Name of the violated constraint/index for an integrity error, else None (internal use)."""
    text = " ".join(str(arg) for arg in getattr(error, "args", ()))
    match = _CONSTRAINT.search(text)
    return (match.group(1) or match.group(2)) if match else None


def is_unique_violation(error: BaseException) -> bool:
    text = " ".join(str(arg) for arg in getattr(error, "args", ()))
    return any(code in text for code in _UNIQUE_CODES)
