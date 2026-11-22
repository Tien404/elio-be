"""Refresh executable API schema and operation metadata from the main routes."""

import json
from pathlib import Path

from app.main import app


def main():
    root = Path(__file__).resolve().parents[1] / "app/contracts"
    schema = app.openapi()
    (root / "openapi.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    previous = {
        item["operationId"]: item for item in json.loads((root / "catalog.json").read_text())
    }
    operations = []
    for path, methods in schema["paths"].items():
        if not path.startswith("/api/v1/"):
            continue
        for method, operation in methods.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            identifier = operation["operationId"]
            item = previous.get(
                identifier,
                {
                    "operationId": identifier,
                    "phase": "MAIN_ADAPTATION",
                    "requirements": [],
                    "screens": [],
                },
            )
            item.update(
                method=method.upper(),
                path=path,
                designPath=path.removeprefix("/api/v1"),
                summary=operation.get("summary", ""),
                description=operation.get("description", ""),
                parameters=operation.get("parameters", []),
                requestBody=operation.get("requestBody"),
                responses=operation["responses"],
                success=[code for code in operation["responses"] if code.startswith("2")],
            )
            operations.append(item)
    (root / "catalog.json").write_text(
        json.dumps(operations, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
