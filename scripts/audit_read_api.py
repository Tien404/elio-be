"""Exercise every GET operation against an isolated snapshot, including legacy rows.

Usage: python -m scripts.audit_read_api --database elio_api_snapshot_test --output /tmp/audit.json
Uses the five seeded demo logins. Never point at the development database: some quiz
reads finalize expired attempts. Copy development data to a disposable *_test schema first.
"""

import argparse
import itertools
import json
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from fastapi.exceptions import ResponseValidationError
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.infrastructure.db.connection import MySQLDatabase
from app.infrastructure.db.sql import Sql
from app.main import create_app

ID_SOURCES = {
    "accountId": ("users", "user_id"),
    "offeringId": ("course_offerings", "offering_id"),
    "courseId": ("courses", "course_id"),
    "assignmentId": ("assignments", "activity_id"),
    "resourceId": ("materials", "material_id"),
    "announcementId": ("announcements", "announcement_id"),
    "fileId": ("file_assets", "file_id"),
    "studentId": ("students", "user_id"),
    "submissionId": ("submissions", "submission_id"),
    "gradeRecordId": ("grades", "grade_id"),
    "groupId": ("assignment_groups", "group_id"),
    "quizId": ("quizzes", "activity_id"),
    "attemptId": ("quiz_attempts", "attempt_id"),
    "questionItemId": ("questions", "question_id"),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"elio_[a-z0-9_]+_test", args.database):
        parser.error("Use a disposable elio_*_test schema containing a development snapshot.")
    original = Settings()
    url = urlsplit(original.database_url.get_secret_value())
    settings = Settings(
        database_url=urlunsplit(url._replace(path=f"/{args.database}")),
        environment="test",
        session_cookie_secure=False,
        private_files_dir=original.private_files_dir,
        credential_outbox_dir=args.output.parent / "outbox",
    )
    app = create_app(settings)
    schema = app.openapi()
    with MySQLDatabase(settings).read_connection() as connection:
        sql = Sql(connection)
        ids = {
            name: [row["id"] for row in sql.all(f"SELECT {column} AS id FROM {table}")]
            for name, (table, column) in ID_SOURCES.items()
        }
        receipts = sql.all(
            "SELECT DISTINCT s.assignment_id,v.request_key FROM submission_versions v "
            "JOIN submissions s ON s.submission_id=v.submission_id"
        )
    records = []
    for actor in ("anonymous", "admin", "teacher", "teacher2", "student", "student2"):
        with TestClient(app) as client:
            if actor != "anonymous":
                login = client.post(
                    "/api/v1/auth/sessions",
                    json={"email": f"{actor}@gmail.com", "password": "12345678"},
                )
                if login.status_code != 201:
                    raise RuntimeError(f"Cannot sign in as snapshot demo actor {actor}.")
            for path, methods in schema["paths"].items():
                if "get" not in methods:
                    continue
                operation = methods["get"]
                keys = re.findall(r"\{([^}]+)\}", path)
                if "requestKey" in keys:
                    cases = [
                        {"assignmentId": row["assignment_id"], "requestKey": row["request_key"]}
                        for row in receipts
                    ]
                else:
                    cases = [
                        dict(zip(keys, values, strict=True))
                        for values in itertools.product(*(ids[key] or [2147483647] for key in keys))
                    ]
                if keys:
                    cases.append(
                        {
                            key: "audit-missing" if key == "requestKey" else 2147483647
                            for key in keys
                        }
                    )
                    cases.append(
                        {key: "audit-missing" if key == "requestKey" else 0 for key in keys}
                    )
                queries = [{"pageSize": 100}]
                if any(p.get("name") == "page" for p in operation.get("parameters", [])):
                    queries += [{"page": 1, "pageSize": 1}, {"page": 99999, "pageSize": 25}]
                if any(p.get("name") == "search" for p in operation.get("parameters", [])):
                    queries.append({"search": "API_AUDIT_NO_MATCH_893"})
                for values, query in itertools.product(cases, queries):
                    actual = path
                    for key, value in values.items():
                        actual = actual.replace("{" + key + "}", str(value))
                    record = {
                        "actor": actor,
                        "method": "GET",
                        "path": path,
                        "url": actual,
                        "query": query,
                    }
                    try:
                        response = client.get(actual, params=query)
                        record["status"] = response.status_code
                        if response.status_code >= 500:
                            record["error"] = response.text[:300]
                    except ResponseValidationError as error:
                        record["exception"] = type(error).__name__
                        record["errors"] = [
                            {"loc": item["loc"], "type": item["type"], "msg": item["msg"]}
                            for item in error.errors()
                        ]
                    except Exception as error:
                        record["exception"] = type(error).__name__
                        record["error"] = str(error)[:300]
                    records.append(record)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n")
    args.output.chmod(0o600)
    failures = [r for r in records if "exception" in r or r.get("status", 0) >= 500]
    print(
        json.dumps(
            {
                "requests": len(records),
                "get_routes": len({r["path"] for r in records}),
                "failures": len(failures),
            }
        )
    )
    for path in sorted({r["path"] for r in failures}):
        print("FAIL", path)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
