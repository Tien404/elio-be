from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.dependencies import get_auth_service
from app.api.schemas.assessment import AssignmentRequest, UpdateAssignmentRequest
from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import csrf_token_for
from app.domain.context import Actor, SessionContext
from app.domain.entities import CourseMembership, CourseRole, CourseState, MembershipStatus
from app.main import create_app
from app.services import submission_service as module
from app.services.access import require_member, require_teacher
from app.services.auth_service import AuthService
from app.services.submission_service import SubmissionService, check_submission_file_access

NOW = datetime(2026, 11, 9, tzinfo=UTC)


def member(role=CourseRole.STUDENT, status=MembershipStatus.ACTIVE):
    return CourseMembership(1, 1, 7, role, status, NOW)


class AccessRepository:
    def __init__(self, state=CourseState.OPEN, membership=None):
        self.offering = SimpleNamespace(state=state, is_open=lambda: state == CourseState.OPEN)
        self.membership = membership or member()

    def get_offering(self, *args, **kwargs):
        return self.offering

    def find_membership(self, *args):
        return self.membership


def test_co_instructor_can_write_but_archived_is_read_only():
    actor = Actor(7, "INSTRUCTOR", False)
    repo = AccessRepository(membership=member(CourseRole.CO_INSTRUCTOR))
    assert require_teacher(repo, actor, 1).course_role == CourseRole.CO_INSTRUCTOR
    repo.offering.state = CourseState.ARCHIVED
    assert require_member(repo, actor, 1)
    with pytest.raises(ApiError, match="CLASS_READ_ONLY"):
        require_teacher(repo, actor, 1)


def test_removed_uploader_cannot_read_their_submission_file(monkeypatch):
    repo = AccessRepository(membership=member(status=MembershipStatus.REMOVED))
    monkeypatch.setattr(module, "CourseRepository", lambda sql: repo)
    with pytest.raises(ApiError, match="NOT_FOUND"):
        check_submission_file_access(
            None, Actor(7, "STUDENT", False), {"offering_id": 1, "uploaded_by": 7}
        )


@pytest.mark.parametrize("offset,accepted", [(-1, False), (0, True), (10, True), (11, False)])
def test_submission_checks_database_window(monkeypatch, offset, accepted):
    row = {
        "activity_id": 1,
        "offering_id": 1,
        "topic_id": None,
        "title": "Work",
        "due_at": NOW + timedelta(seconds=5),
        "max_score": 10,
        "status": "PUBLISHED",
        "instructions": "",
        "version": 1,
        "open_at": NOW,
        "cutoff_at": NOW + timedelta(seconds=10),
    }
    repo = SimpleNamespace(
        get_assignment=lambda *a, **k: row,
        db_now=lambda: NOW + timedelta(seconds=offset),
        has_grade=lambda id: False,
    )
    monkeypatch.setattr(module, "CourseRepository", lambda sql: AccessRepository())
    monkeypatch.setattr(module, "AssessmentRepository", lambda sql: repo)
    check = SubmissionService._can_submit_to(Actor(7, "STUDENT", False), 1, 1)
    if accepted:
        check(None)
    else:
        with pytest.raises(ApiError, match="SUBMISSION_WINDOW_CLOSED"):
            check(None)


def test_assignment_requires_ordered_aware_schedule_and_attachment_limit():
    body = {
        "title": "Work",
        "status": "DRAFT",
        "openAt": NOW,
        "dueAt": NOW,
        "cutoffAt": NOW,
        "maxScore": 10,
        "weight": 20,
        "fileIds": [],
    }
    assert AssignmentRequest(**body).cutoffAt == NOW
    for changes in [
        {"cutoffAt": NOW - timedelta(seconds=1)},
        {"dueAt": NOW.replace(tzinfo=None)},
        {"weight": 101},
        {"fileIds": [1, 2, 3, 4, 5, 6]},
    ]:
        with pytest.raises(ValidationError):
            AssignmentRequest(**{**body, **changes})
    with pytest.raises(ValidationError):
        UpdateAssignmentRequest(cutoffAt=None)


def test_restricted_session_bootstrap_supports_reload_without_opening_me():
    actor = Actor(7, "STUDENT", True)
    session = SessionContext(
        actor=actor, session_id=1, token="session-token", expires_at=NOW + timedelta(days=1)
    )
    me = {
        "account": {
            "id": 7,
            "displayName": "Student",
            "status": "ACTIVE",
            "role": "STUDENT",
            "mustChangePassword": True,
        },
        "email": "student@elio.test",
        "canCreateCourse": False,
        "version": 1,
    }
    service = AuthService(None, Settings(_env_file=None))
    service.resolve_session = lambda token: session
    service.get_me = lambda **kw: me
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[get_auth_service] = lambda: service
    with TestClient(app) as client:
        client.cookies.set("elio_session", "session-token")
        response = client.get("/api/v1/auth/session")
        assert response.status_code == 200
        assert response.json()["session"]["csrfToken"] == csrf_token_for("session-token")
        assert response.json()["session"]["restricted"] is True
        assert response.headers["cache-control"] == "no-store"
        assert client.get("/api/v1/me").status_code == 403
        assert client.post("/api/v1/offerings/join", json={"code": "ABC123"}).status_code == 403


def test_published_assignment_rejects_shorten_and_edit_after_grade(monkeypatch):
    row = {
        "activity_id": 1,
        "offering_id": 1,
        "topic_id": None,
        "title": "Work",
        "due_at": NOW + timedelta(days=1),
        "max_score": 10,
        "weight_pct": 20,
        "is_mandatory": True,
        "status": "PUBLISHED",
        "instructions": "",
        "version": 1,
        "open_at": NOW,
        "cutoff_at": NOW + timedelta(days=2),
    }
    repo = SimpleNamespace(
        get_assignment=lambda *a, **k: row, attachment_ids=lambda id: [], has_grade=lambda id: True
    )
    monkeypatch.setattr(module, "AssessmentRepository", lambda sql: repo)
    monkeypatch.setattr(
        module,
        "CourseRepository",
        lambda sql: AccessRepository(membership=member(CourseRole.CO_INSTRUCTOR)),
    )
    service = SubmissionService(SimpleNamespace(transaction=lambda: nullcontext(None)))
    for changes in [{"dueAt": NOW}, {"cutoffAt": NOW + timedelta(days=3)}, {"title": "Changed"}]:
        with pytest.raises(ApiError):
            service.update_assignment(
                actor=Actor(7, "INSTRUCTOR", False),
                assignment_id=1,
                expected_version=1,
                changes=changes,
            )


def test_admin_restore_preserves_private_metadata(monkeypatch):
    from app.services import course_service as courses

    offering = SimpleNamespace(state=CourseState.ARCHIVED, version=4)
    stored = {}
    repo = SimpleNamespace(
        get_offering=lambda *a, **k: offering,
        metadata=lambda id: {
            "learning_information": "Private syllabus",
            "join_code": "ABC123",
            "join_code_enabled": True,
        },
        offering_summary=lambda id: {},
        update_offering=lambda id, data: stored.update(data),
    )
    monkeypatch.setattr(courses, "CourseRepository", lambda sql: repo)
    monkeypatch.setattr(
        courses, "AuditRepository", lambda sql: SimpleNamespace(record=lambda **kw: None)
    )
    service = courses.CourseService(SimpleNamespace(transaction=lambda: nullcontext(None)))
    service._require_lead = lambda *a, **k: offering
    service._workspace_view = lambda *a, **k: {
        "title": "Class",
        "semester": "2026-1",
        "sectionCode": "01",
        "status": "ARCHIVED",
        "lead": {"status": "ACTIVE"},
        "learningInformation": None,
        "joinCode": None,
        "joinEnabled": False,
    }
    service.restore_offering(
        actor=Actor(1, "ADMIN", False), offering_id=1, expected_version=4, reason="Resume"
    )
    assert stored["status"] == "OPEN"
    assert stored["learningInformation"] == "Private syllabus"
    assert stored["joinCode"] == "ABC123" and stored["joinEnabled"] is True
