import json
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

CONTRACTS = Path(__file__).parents[1] / "app/contracts"
CATALOG = json.loads((CONTRACTS / "catalog.json").read_text())


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


@pytest.mark.parametrize("operation", CATALOG, ids=lambda op: op["operationId"])
def test_every_business_route_is_explicit_501_not_a_mock_success(client, operation):
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
    assert len(CATALOG) == 78
    for op in CATALOG:
        actual = schema["paths"][op["path"]][op["method"].lower()]
        assert actual["operationId"] == op["operationId"]
        assert "501" in actual["responses"]
        assert not any(code.startswith("2") for code in actual["responses"])
        assert "requestBody" not in actual
        assert "security" not in actual
        assert "x-implementation-status" not in actual
        names = re.findall(r"\{([^}]+)\}", op["path"])
        paths = {p["name"]: p for p in actual.get("parameters", []) if p["in"] == "path"}
        assert set(paths) == set(names)
        assert all(p["required"] for p in paths.values())
    confirm = schema["paths"]["/api/v1/assignments/{assignmentId}/submissions"]["post"]
    assignment_id = next(p for p in confirm["parameters"] if p["name"] == "assignmentId")
    assert assignment_id["schema"]["type"] == "integer"
    assert assignment_id["schema"]["minimum"] == 1
    assert assignment_id["schema"]["maximum"] == 2147483647
    assert "SessionView" not in schema.get("components", {}).get("schemas", {})
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200


@pytest.mark.parametrize("value", ["0", "-1", "not-an-id", "2147483648"])
def test_invalid_path_id_uses_safe_validation_error(client, value):
    response = client.get(f"/api/v1/submissions/{value}")
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"


def test_invalid_receipt_key_uses_safe_validation_error(client):
    response = client.get("/api/v1/assignments/1/submission-receipts/short")
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"


def test_portable_contract_has_complete_internal_references():
    spec = json.loads((CONTRACTS / "openapi.json").read_text())

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


def test_no_business_schema_is_falsely_installed():
    assert not list((Path(__file__).parents[1] / "sql/migrations").glob("*.sql"))
    model = json.loads((Path(__file__).parents[1] / "app/contracts/logical-model.json").read_text())
    assert len(model) == 38  # Logical design only, not 38 installed SQL Server tables.
