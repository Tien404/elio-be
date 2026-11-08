import struct
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from importlib import import_module

from app.core.config import Settings

SQL_SS_TIMESTAMPOFFSET = -155


def _datetimeoffset(value: bytes | None) -> datetime | None:
    """pyodbc has no native DATETIMEOFFSET support; decode the ODBC struct to an aware UTC datetime."""
    if value is None:
        return None
    year, month, day, hour, minute, second, fraction, tz_hour, tz_minute = struct.unpack(
        "<6hI2h", value
    )
    local = datetime(year, month, day, hour, minute, second, fraction // 1000)
    offset = timedelta(hours=tz_hour, minutes=tz_minute)
    return (local - offset).replace(tzinfo=timezone.utc)


class DatabaseUnavailable(RuntimeError):
    """Safe connection/probe error; never expose ODBC diagnostics to HTTP clients."""


def load_driver():
    # Load ODBC only when opening a database connection.
    try:
        return import_module("pyodbc")
    except (ImportError, OSError):
        raise DatabaseUnavailable("ODBC runtime is unavailable.") from None


class PyodbcDatabase:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _connect(self, *, readonly: bool):
        driver = load_driver()
        value = self.settings.odbc_connection_string.get_secret_value()
        if not value.strip():
            raise DatabaseUnavailable("SQL Server connection is not configured.")
        connection = None
        try:
            connection = driver.connect(
                value,
                autocommit=False,
                readonly=readonly,
                timeout=self.settings.db_connect_timeout_seconds,
            )
            connection.timeout = self.settings.db_query_timeout_seconds
            if hasattr(connection, "add_output_converter"):
                connection.add_output_converter(SQL_SS_TIMESTAMPOFFSET, _datetimeoffset)
            return connection
        except driver.Error:
            if connection is not None:
                try:
                    connection.close()
                except driver.Error:
                    pass
            raise DatabaseUnavailable("SQL Server connection is unavailable.") from None

    @contextmanager
    def transaction(self):
        """One connection per use case; repositories must never commit individually."""
        connection = self._connect(readonly=False)
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def read_connection(self):
        """Read intent for probes/queries; always end the transaction and close."""
        connection = self._connect(readonly=True)
        try:
            yield connection
        finally:
            try:
                connection.rollback()
            finally:
                connection.close()

    def check_connection(self):
        driver = load_driver()
        try:
            with self.read_connection() as connection:
                cursor = connection.cursor()
                try:
                    row = cursor.execute("SELECT 1").fetchone()
                    if row is None or row[0] != 1:
                        raise DatabaseUnavailable("SQL Server probe failed.")
                finally:
                    cursor.close()
        except driver.Error:
            raise DatabaseUnavailable("SQL Server probe failed.") from None


class PyodbcRepository:
    def __init__(self, database: PyodbcDatabase):
        self.database = database

    def transaction(self):
        return self.database.transaction()
