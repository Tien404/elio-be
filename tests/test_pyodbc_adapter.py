"""Adapter behavior only; fake DB-API is NOT SQL Server integration evidence."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.infrastructure.db import connection as module
from app.infrastructure.db.connection import DatabaseUnavailable, PyodbcDatabase, PyodbcRepository
from app.main import create_app


class DriverError(Exception):
    pass


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, *params):
        self.connection.events.append(("execute", sql, params))
        if self.connection.query_error:
            raise DriverError("private driver diagnostics: password=never-echo-this")
        return self

    def fetchone(self):
        return self.connection.row

    def fetchall(self):
        return []  # e.g. no applied migrations

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

    def connect(value, **options):
        calls.append((value, options))
        return connection

    driver = SimpleNamespace(Error=DriverError, connect=connect)
    monkeypatch.setattr(module, "load_driver", lambda: driver)
    settings = Settings(odbc_connection_string="DRIVER={test};PWD=never-echo-this;")
    return PyodbcDatabase(settings), connection, calls, driver


def test_transaction_shares_connection_and_commits_once(adapter):
    database, connection, calls, _ = adapter
    with PyodbcRepository(database).transaction() as shared:
        assert shared is connection
        assert connection.events == []
        shared.cursor().execute("SELECT ?", "example-value")
    assert connection.events[-2:] == ["commit", "close"]
    assert len(calls) == 1
    assert calls[0][1] == {"autocommit": False, "readonly": False, "timeout": 2}
    assert connection.timeout == 5


def test_use_case_error_rolls_back_all_writes_and_closes(adapter):
    database, connection, _, _ = adapter
    with pytest.raises(ValueError, match="policy failure"):
        with database.transaction():
            raise ValueError("policy failure")
    assert connection.events == ["rollback", "close"]


def test_failed_commit_is_not_reported_as_success(adapter):
    database, connection, _, _ = adapter
    connection.commit_error = True
    with pytest.raises(DriverError):
        with database.transaction():
            pass
    assert connection.events == ["commit", "rollback", "close"]


def test_read_context_never_commits(adapter):
    database, connection, calls, _ = adapter
    with database.read_connection():
        pass
    assert calls[0][1]["readonly"] is True
    assert connection.events == ["rollback", "close"]


def test_read_error_still_ends_transaction_and_closes(adapter):
    database, connection, _, _ = adapter
    with pytest.raises(ValueError):
        with database.read_connection():
            raise ValueError("read failed")
    assert connection.events == ["rollback", "close"]


def test_probe_closes_cursor_and_connection(adapter):
    database, connection, _, _ = adapter
    database.check_connection()
    assert connection.events == [("execute", "SELECT 1", ()), "cursor.close", "rollback", "close"]


def test_probe_error_is_safe_and_cleans_up(adapter):
    database, connection, _, _ = adapter
    connection.query_error = True
    with pytest.raises(DatabaseUnavailable) as error:
        database.check_connection()
    assert "never-echo-this" not in str(error.value)
    assert connection.events[-3:] == ["cursor.close", "rollback", "close"]


def test_connection_error_does_not_expose_driver_diagnostics(adapter):
    database, _, _, driver = adapter

    def fail(*args, **kwargs):
        raise DriverError("PWD=never-echo-this")

    driver.connect = fail
    with pytest.raises(DatabaseUnavailable) as error:
        with database.transaction():
            pytest.fail("must not reach transaction body")
    assert "never-echo-this" not in str(error.value)


def test_unconfigured_connection_never_connects(adapter):
    _, _, calls, _ = adapter
    database = PyodbcDatabase(Settings(odbc_connection_string=""))
    with pytest.raises(DatabaseUnavailable):
        with database.transaction():
            pytest.fail("must not reach transaction body")
    assert calls == []


@pytest.mark.parametrize("error_type", [ImportError, OSError])
def test_missing_os_runtime_is_a_safe_unavailable_error(monkeypatch, error_type):
    def fail(name):
        raise error_type("internal OS loader paths")

    monkeypatch.setattr(module, "import_module", fail)
    with pytest.raises(DatabaseUnavailable) as error:
        module.load_driver()
    assert "internal OS" not in str(error.value)


def test_successful_db_probe_still_does_not_claim_schema_ready(adapter):
    database, _, _, _ = adapter
    with TestClient(create_app(database.settings)) as client:
        response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["code"] == "SCHEMA_NOT_INSTALLED"


def test_http_db_failure_does_not_leak_private_odbc_diagnostics(adapter):
    database, connection, _, _ = adapter
    connection.query_error = True
    with TestClient(create_app(database.settings)) as client:
        response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["code"] == "DATABASE_UNAVAILABLE"
    assert "never-echo-this" not in response.text


def test_startup_live_docs_and_business_stubs_do_not_load_odbc(monkeypatch):
    def unexpected():
        pytest.fail("ODBC must not load for startup/docs/live/501")

    monkeypatch.setattr(module, "load_driver", unexpected)
    with TestClient(create_app(Settings(odbc_connection_string=""))) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/docs").status_code == 200
        assert client.get("/openapi.json").status_code == 200
        # request validation happens before any database access
        assert client.post("/api/v1/auth/sessions").status_code == 400
        assert client.get("/api/v1/dashboard").status_code == 501
