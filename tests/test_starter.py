import json
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

CONTRACTS = Path(__file__).parents[1] / "app/contracts"
CATALOG = json.loads((CONTRACTS / "catalog.json").read_text(encoding="utf-8"))


@pytest.fixture
def client():
    settings = Settings(
        environment="test",
        odbc_connection_string="",
        db_connect_timeout_seconds=1,
    )
    with TestClient(create_app(settings)) as value:
        yield value


def test_live_reports_process_status(client):
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_unreachable_database_is_not_ready_and_does_not_leak_credentials(client):
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["code"] == "DATABASE_UNAVAILABLE"
    assert "nobody" not in response.text


def test_unknown_route_uses_problem_without_echoing_input(client):
    response = client.get("/no-such-endpoint?password=never-echo-this")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "never-echo-this" not in response.text


def _implemented(client) -> set[str]:
    """Operations whose route no longer declares the 501 placeholder."""
    schema = client.get("/openapi.json").json()
    return {
        op["operationId"]
        for op in CATALOG
        if "501" not in schema["paths"][op["path"]][op["method"].lower()]["responses"]
    }


@pytest.mark.parametrize("operation", CATALOG, ids=lambda op: op["operationId"])
def test_unimplemented_routes_are_explicit_501_not_a_mock_success(client, operation):
    if operation["operationId"] in _implemented(client):
        pytest.skip("implemented; covered by integration tests")
    path = re.sub(
        r"\{([^}]+)\}",
        lambda match: "demo_request_key_0001" if match[1] == "requestKey" else "1",
        operation["path"],
    )
    response = client.request(operation["method"], path)
    assert response.status_code == 501, (operation["operationId"], response.text)
    body = response.json()
    assert body["status"] == 501 and body["code"] == "NOT_IMPLEMENTED"
    assert body["detail"].startswith("Operation unavailable:")


def test_openapi_is_generated_from_route_declarations(client):
    schema = client.get("/openapi.json").json()
    assert client.app.openapi.__func__ is FastAPI.openapi
    assert len(CATALOG) == len({op["operationId"] for op in CATALOG})
    implemented = _implemented(client)
    for op in CATALOG:
        actual = schema["paths"][op["path"]][op["method"].lower()]
        assert actual["operationId"] == op["operationId"]
        assert "x-implementation-status" not in actual
        if op["operationId"] in implemented:
            # Real routes declare the contract's success status.
            expected = set(op["success"])
            assert expected & set(actual["responses"]), (op["operationId"], actual["responses"])
        else:
            assert not any(code.startswith("2") for code in actual["responses"])
            assert "requestBody" not in actual
        names = re.findall(r"\{([^}]+)\}", op["path"])
        paths = {p["name"]: p for p in actual.get("parameters", []) if p["in"] == "path"}
        assert set(paths) == set(names)
        assert all(p["required"] for p in paths.values())
    confirm = schema["paths"]["/api/v1/assignments/{assignmentId}/submissions"]["post"]
    assignment_id = next(p for p in confirm["parameters"] if p["name"] == "assignmentId")
    assert assignment_id["schema"]["type"] == "integer"
    assert assignment_id["schema"]["minimum"] == 1
    assert assignment_id["schema"]["maximum"] == 2147483647
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200


@pytest.mark.parametrize("value", ["0", "-1", "not-an-id", "2147483648"])
def test_invalid_path_id_uses_safe_validation_error(client, value):
    # a placeholder route without login, so only path validation applies
    response = client.get(f"/api/v1/groups/{value}")
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"


def test_invalid_receipt_key_uses_safe_validation_error(client):
    response = client.get("/api/v1/assignments/1/submission-receipts/short")
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"


def test_portable_contract_has_complete_internal_references():
    spec = json.loads((CONTRACTS / "openapi.json").read_text(encoding="utf-8"))

    def visit(value):
        if isinstance(value, dict):
            if "$ref" in value:
                assert value["$ref"].startswith("#/")
                target = spec
                for key in value["$ref"][2:].split("/"):
                    target = target[key]
                assert target is not None
            for sub in value.values():
                visit(sub)
        elif isinstance(value, list):
            for sub in value:
                visit(sub)

    visit(spec)


def test_migrations_create_every_logical_model_table():
    root = Path(__file__).parents[1]
    model = json.loads((root / "app/contracts/logical-model.json").read_text(encoding="utf-8"))
    assert len(model) == 38
    sql = "\n".join(
        p.read_text(encoding="utf-8") for p in sorted((root / "sql/migrations").glob("*.sql"))
    )
    created = set(re.findall(r"CREATE TABLE dbo\.(\w+)", sql))
    team_additions = {"course_registrations"}  # 006: MVP sign-up requests, not in the model
    assert created - {"schema_migrations"} == set(model) | team_additions
