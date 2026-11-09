from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.infrastructure.db import connection as module
from app.infrastructure.db.connection import DatabaseUnavailable, MySQLDatabase, connection_options
from app.infrastructure.db.sql import Sql, is_unique_violation, like_literal, violated_constraint
from app.main import create_app


class DriverError(Exception):
    pass


class FakeCursor:
    description = [("value",)]
    lastrowid = 42
    rowcount = 1

    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def execute(self, sql, params=None):
        self.connection.events.append(("execute", sql, params))
        if self.connection.query_error and sql == "SELECT 1":
            raise DriverError("password=never-echo-this")
        return 1

    def fetchone(self):
        return self.connection.row

    def fetchall(self):
        return []

    def close(self):
        self.connection.events.append("cursor.close")


class FakeConnection:
    def __init__(self):
        self.events = []
        self.commit_error = False
        self.query_error = False
        self.row = (1,)

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.events.append("commit")
        if self.commit_error:
            raise DriverError("commit acknowledgement lost")

    def rollback(self):
        self.events.append("rollback")

    def close(self):
        self.events.append("close")


@pytest.fixture
def adapter(monkeypatch):
    connection = FakeConnection()
    calls = []

    def connect(**options):
        calls.append(options)
        return connection

    driver = SimpleNamespace(Error=DriverError, connect=connect)
    monkeypatch.setattr(module, "load_driver", lambda: driver)
    settings = Settings(
        _env_file=None, database_url="mysql://tester:never-echo-this@127.0.0.1/elio_test"
    )
    return MySQLDatabase(settings), connection, calls, driver


def test_transaction_uses_one_connection_and_commits_once(adapter):
    database, connection, calls, _ = adapter
    with database.transaction() as shared:
        assert shared is connection
        assert Sql(shared).insert("INSERT INTO things (name) VALUES (%s)", "x") == 42
    assert connection.events[-2:] == ["commit", "close"]
    assert len(calls) == 1
    assert calls[0]["autocommit"] is False
    assert calls[0]["read_timeout"] == 5
    assert calls[0]["init_command"] == "SET time_zone = '+00:00'"


@pytest.mark.parametrize("commit_error", [False, True])
def test_failed_transaction_rolls_back_and_closes(adapter, commit_error):
    database, connection, _, _ = adapter
    connection.commit_error = commit_error
    with pytest.raises(DriverError if commit_error else ValueError):
        with database.transaction():
            if not commit_error:
                raise ValueError("policy failure")
    assert connection.events[-2:] == ["rollback", "close"]


def test_read_only_context_never_commits_even_on_error(adapter):
    database, connection, _, _ = adapter
    with pytest.raises(ValueError):
        with database.read_connection():
            raise ValueError("query failed")
    assert ("execute", "SET TRANSACTION READ ONLY", None) in connection.events
    assert "commit" not in connection.events
    assert connection.events[-2:] == ["rollback", "close"]


def test_connection_error_is_safe(adapter):
    database, _, _, driver = adapter

    def fail(**kwargs):
        raise DriverError("password=never-echo-this")

    driver.connect = fail
    with pytest.raises(DatabaseUnavailable, match="MySQL connection is unavailable"):
        with database.transaction():
            pytest.fail("unreachable")


@pytest.mark.parametrize(
    "url",
    [
        "",
        "postgresql://u:p@localhost/db",
        "mysql://u:p@localhost",
        "mysql://u:p@localhost:bad/db",
        "mysql://u:p@localhost/db?ssl=false",
    ],
)
def test_invalid_url_never_connects(adapter, url):
    _, _, calls, _ = adapter
    with pytest.raises(DatabaseUnavailable):
        MySQLDatabase(Settings(_env_file=None, database_url=url))._connect(readonly=False)
    assert not calls


def test_url_decodes_password_without_leaking_it():
    assert connection_options("mysql://user:a%40b%23c@localhost/db")["password"] == "a@b#c"
    assert "a%40b" not in repr(
        Settings(_env_file=None, database_url="mysql://user:a%40b@localhost/db")
    )


def test_missing_driver_is_safe(monkeypatch):
    def fail(name):
        raise ImportError("private loader paths")

    monkeypatch.setattr(module, "import_module", fail)
    with pytest.raises(DatabaseUnavailable, match="MySQL driver is unavailable"):
        module.load_driver()


def test_probe_does_not_claim_missing_schema_ready(adapter):
    database, _, _, _ = adapter
    with TestClient(create_app(database.settings)) as client:
        response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["code"] == "SCHEMA_NOT_INSTALLED"


def test_http_failure_does_not_expose_diagnostics(adapter):
    database, connection, _, _ = adapter
    connection.query_error = True
    with TestClient(create_app(database.settings)) as client:
        response = client.get("/health/ready")
    assert response.status_code == 503
    assert "never-echo-this" not in response.text
    assert connection.events[-3:] == ["cursor.close", "rollback", "close"]


def test_docs_and_live_do_not_connect(monkeypatch):
    def fail():
        pytest.fail("Must not load driver")

    monkeypatch.setattr(module, "load_driver", fail)
    with TestClient(create_app(Settings(_env_file=None, database_url=""))) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/docs").status_code == 200
        assert client.post("/api/v1/auth/sessions").status_code == 400


def test_datetime_parameters_and_results_use_utc(adapter):
    _, connection, _, _ = adapter
    instant = datetime(2026, 11, 9, 17, tzinfo=timezone(timedelta(hours=7)))
    connection.row = (datetime(2026, 11, 9, 10),)
    result = Sql(connection).scalar("SELECT %s", instant)
    assert result == instant.astimezone(UTC)
    assert connection.events[0][2] == (datetime(2026, 11, 9, 10),)


def test_mysql_unique_errors_and_literal_search():
    error = DriverError(1062, "Duplicate entry 'x' for key 'users.UQ_users_email'")
    assert is_unique_violation(error)
    assert violated_constraint(error) == "UQ_users_email"
    assert not is_unique_violation(DriverError(1452, "FK failed"))
    assert like_literal("a!b%_[]") == "a!!b!%!_[]"
