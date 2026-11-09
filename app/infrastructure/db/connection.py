from contextlib import contextmanager
from importlib import import_module
from urllib.parse import unquote, urlsplit

from app.core.config import Settings


class DatabaseUnavailable(RuntimeError):
    pass


def load_driver():
    try:
        return import_module("pymysql")
    except (ImportError, OSError):
        raise DatabaseUnavailable("MySQL driver is unavailable.") from None


def connection_options(url: str) -> dict:
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "mysql"
            or not parsed.hostname
            or not parsed.username
            or not parsed.path.strip("/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError
        return {
            "host": parsed.hostname,
            "port": parsed.port or 3306,
            "user": unquote(parsed.username),
            "password": unquote(parsed.password or ""),
            "database": unquote(parsed.path.lstrip("/")),
        }
    except ValueError:
        raise DatabaseUnavailable(
            "Configure ELIO_DATABASE_URL as mysql://user:password@host:port/database."
        ) from None


class MySQLDatabase:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _connect(self, *, readonly: bool):
        options = connection_options(self.settings.database_url.get_secret_value())
        driver = load_driver()
        connection = None
        try:
            connection = driver.connect(
                **options,
                charset="utf8mb4",
                autocommit=False,
                connect_timeout=self.settings.db_connect_timeout_seconds,
                read_timeout=self.settings.db_query_timeout_seconds,
                write_timeout=self.settings.db_query_timeout_seconds,
                init_command="SET time_zone = '+00:00'",
            )
            with connection.cursor() as cursor:
                cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
                cursor.execute("SET SESSION group_concat_max_len = 4096")
                cursor.execute(
                    "SET TRANSACTION READ ONLY" if readonly else "SET TRANSACTION READ WRITE"
                )
            return connection
        except driver.Error:
            if connection is not None:
                connection.close()
            raise DatabaseUnavailable("MySQL connection is unavailable.") from None

    @contextmanager
    def transaction(self):
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
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    row = cursor.fetchone()
                    if row is None or row[0] != 1:
                        raise DatabaseUnavailable("MySQL probe failed.")
        except driver.Error:
            raise DatabaseUnavailable("MySQL probe failed.") from None
