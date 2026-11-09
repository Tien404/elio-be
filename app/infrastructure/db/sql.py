import re
from datetime import UTC, datetime
from typing import Any


class Sql:
    def __init__(self, connection: Any):
        self.connection = connection

    def _run(self, statement: str, params: tuple):
        cursor = self.connection.cursor()
        try:
            values = tuple(
                value.astimezone(UTC).replace(tzinfo=None)
                if isinstance(value, datetime) and value.tzinfo
                else value
                for value in params
            )
            cursor.execute(statement, values or None)
            return cursor
        except BaseException:
            cursor.close()
            raise

    @staticmethod
    def _row(cursor, row) -> dict[str, Any]:
        return {
            column[0]: value.replace(tzinfo=UTC) if isinstance(value, datetime) else value
            for column, value in zip(cursor.description, row)
        }

    def all(self, statement: str, *params: Any) -> list[dict[str, Any]]:
        cursor = self._run(statement, params)
        try:
            return [self._row(cursor, row) for row in cursor.fetchall()]
        finally:
            cursor.close()

    def one(self, statement: str, *params: Any) -> dict[str, Any] | None:
        cursor = self._run(statement, params)
        try:
            row = cursor.fetchone()
            return None if row is None else self._row(cursor, row)
        finally:
            cursor.close()

    def scalar(self, statement: str, *params: Any) -> Any:
        cursor = self._run(statement, params)
        try:
            row = cursor.fetchone()
            value = None if row is None else row[0]
            return value.replace(tzinfo=UTC) if isinstance(value, datetime) else value
        finally:
            cursor.close()

    def insert(self, statement: str, *params: Any) -> int:
        cursor = self._run(statement, params)
        try:
            return cursor.lastrowid
        finally:
            cursor.close()

    def execute(self, statement: str, *params: Any) -> int:
        cursor = self._run(statement, params)
        try:
            return cursor.rowcount
        finally:
            cursor.close()


def violated_constraint(error: BaseException) -> str | None:
    text = " ".join(str(arg) for arg in getattr(error, "args", ()))
    match = re.search(r"(?:for key|CONSTRAINT) [`'\"]([^`'\"]+)[`'\"]", text, re.IGNORECASE)
    return match[1].rsplit(".", 1)[-1] if match else None


def is_unique_violation(error: BaseException) -> bool:
    return bool(error.args and error.args[0] == 1062)


def like_literal(text: str) -> str:
    return text.replace("!", "!!").replace("%", "!%").replace("_", "!_")
