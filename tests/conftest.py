"""Shared fixtures. Integration tests run against a real, isolated SQL Server database.

Set ELIO_TEST_ODBC_CONNECTION_STRING (environment or .env) to an ELIO database created with
`sql/apply_migrations.ps1 -Database elio_test`. Every test starts from empty tables.
Never point this at a database whose data you want to keep.
"""

import os
from pathlib import Path

import pytest
from dotenv import dotenv_values
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.infrastructure.db.connection import PyodbcDatabase
from app.main import create_app

ROOT = Path(__file__).parents[1]

# Children before parents; pointer columns cleared first to break cycles.
_CLEANUP = [
    "DELETE dbo.attempt_answers",
    "DELETE dbo.quiz_attempts",
    "DELETE dbo.quiz_snapshot_options",
    "DELETE dbo.quiz_snapshot_questions",
    "DELETE dbo.quiz_questions",
    "DELETE dbo.question_options",
    "DELETE dbo.questions",
    "DELETE dbo.question_banks",
    "DELETE dbo.notifications",
    "DELETE dbo.announcements",
    "DELETE dbo.audit_entries",
    "UPDATE dbo.grades SET draft_revision_no = NULL, published_revision_no = NULL, published_at = NULL",
    "DELETE dbo.grade_revisions",
    "DELETE dbo.grades",
    "DELETE dbo.submission_files",
    "DELETE dbo.submission_versions",
    "DELETE dbo.submission_roster",
    "DELETE dbo.submissions",
    "DELETE dbo.group_members",
    "DELETE dbo.assignment_groups",
    "DELETE dbo.assignment_attachments",
    "DELETE dbo.file_materials",
    "DELETE dbo.text_materials",
    "DELETE dbo.link_materials",
    "DELETE dbo.material_completions",
    "DELETE dbo.materials",
    "DELETE dbo.file_assets",
    "DELETE dbo.quizzes",
    "DELETE dbo.assignments",
    "DELETE dbo.activities",
    "DELETE dbo.topics",
    "DELETE dbo.course_registrations",
    "DELETE dbo.course_memberships",
    "DELETE dbo.course_offerings",
    "DELETE dbo.courses",
    "DELETE dbo.user_sessions",
    "UPDATE dbo.users SET created_by = NULL",
    "DELETE dbo.students",
    "DELETE dbo.instructors",
    "DELETE dbo.admins",
    "DELETE dbo.users",
]


def _test_connection_string() -> str:
    value = os.environ.get("ELIO_TEST_ODBC_CONNECTION_STRING")
    if not value and (ROOT / ".env").exists():
        value = dotenv_values(ROOT / ".env").get("ELIO_TEST_ODBC_CONNECTION_STRING")
    return value or ""


@pytest.fixture
def db_settings(tmp_path) -> Settings:
    connection_string = _test_connection_string()
    if not connection_string:
        pytest.skip("ELIO_TEST_ODBC_CONNECTION_STRING not set; SQL Server integration skipped.")
    if "elio_dev" in connection_string.lower():
        pytest.exit("Refusing to run destructive tests against elio_dev.")
    return Settings(
        _env_file=None,
        environment="test",
        odbc_connection_string=connection_string,
        db_connect_timeout_seconds=5,
        db_query_timeout_seconds=30,
        session_cookie_secure=False,  # TestClient talks plain HTTP
        private_files_dir=tmp_path / "private",
        credential_outbox_dir=tmp_path / "outbox",
    )


@pytest.fixture
def database(db_settings) -> PyodbcDatabase:
    database = PyodbcDatabase(db_settings)
    with database.transaction() as connection:
        cursor = connection.cursor()
        try:
            for statement in _CLEANUP:
                cursor.execute(statement)
        finally:
            cursor.close()
    return database


@pytest.fixture
def api(db_settings, database):
    with TestClient(create_app(db_settings)) as client:
        yield client
