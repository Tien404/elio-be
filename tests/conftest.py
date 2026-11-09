"""Shared fixtures. Integration tests run against a real, isolated MySQL database.

Set ELIO_TEST_DATABASE_URL (environment or .env) to an ELIO database created with
`python -m scripts.migrate`. Every test starts from empty tables.
Never point this at a database whose data you want to keep.
"""

import os
from pathlib import Path

import pytest
from dotenv import dotenv_values
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.infrastructure.db.connection import MySQLDatabase, connection_options
from app.main import create_app

ROOT = Path(__file__).parents[1]

# Children before parents; pointer columns cleared first to break cycles.
_CLEANUP = [
    "DELETE FROM attempt_answers",
    "DELETE FROM quiz_attempts",
    "DELETE FROM quiz_snapshot_options",
    "DELETE FROM quiz_snapshot_questions",
    "DELETE FROM quiz_questions",
    "DELETE FROM question_options",
    "DELETE FROM questions",
    "DELETE FROM question_banks",
    "DELETE FROM notifications",
    "DELETE FROM announcements",
    "DELETE FROM audit_entries",
    "UPDATE grades SET draft_revision_no = NULL, published_revision_no = NULL, published_at = NULL",
    "DELETE FROM grade_revisions",
    "DELETE FROM grades",
    "DELETE FROM submission_files",
    "DELETE FROM submission_versions",
    "DELETE FROM submission_roster",
    "DELETE FROM submissions",
    "DELETE FROM group_members",
    "DELETE FROM assignment_groups",
    "DELETE FROM assignment_attachments",
    "DELETE FROM file_materials",
    "DELETE FROM text_materials",
    "DELETE FROM link_materials",
    "DELETE FROM material_completions",
    "DELETE FROM materials",
    "DELETE FROM file_assets",
    "DELETE FROM quizzes",
    "DELETE FROM assignments",
    "DELETE FROM activities",
    "DELETE FROM topics",
    "DELETE FROM course_registrations",
    "DELETE FROM course_memberships",
    "DELETE FROM course_offerings",
    "DELETE FROM courses",
    "DELETE FROM user_sessions",
    "UPDATE users SET created_by = NULL",
    "DELETE FROM students",
    "DELETE FROM instructors",
    "DELETE FROM admins",
    "DELETE FROM users",
]


def _test_connection_string() -> str:
    value = os.environ.get("ELIO_TEST_DATABASE_URL")
    if not value and (ROOT / ".env").exists():
        value = dotenv_values(ROOT / ".env").get("ELIO_TEST_DATABASE_URL")
    return value or ""


@pytest.fixture
def db_settings(tmp_path) -> Settings:
    connection_string = _test_connection_string()
    if not connection_string:
        pytest.skip("ELIO_TEST_DATABASE_URL not set; MySQL integration skipped.")
    if not connection_options(connection_string)["database"].endswith("_test"):
        pytest.exit("Tests require a database name ending in _test.")
    return Settings(
        _env_file=None,
        environment="test",
        database_url=connection_string,
        db_connect_timeout_seconds=5,
        db_query_timeout_seconds=30,
        session_cookie_secure=False,  # TestClient talks plain HTTP
        private_files_dir=tmp_path / "private",
        credential_outbox_dir=tmp_path / "outbox",
    )


@pytest.fixture
def database(db_settings) -> MySQLDatabase:
    database = MySQLDatabase(db_settings)
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
