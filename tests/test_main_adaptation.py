"""User-selected main policies, exercised against an isolated MySQL schema."""

from tests.helpers import class_with_student, create_user
from tests.test_quizzes import _published, _run_sql, _true_false
from tests.test_submissions import _box, _submit, _upload


def close_assignment(api, aid):
    _run_sql(
        api,
        "UPDATE assignments SET open_at=UTC_TIMESTAMP(6)-INTERVAL 3 HOUR,due_at=UTC_TIMESTAMP(6)-INTERVAL 2 HOUR,cutoff_at=UTC_TIMESTAMP(6)-INTERVAL 1 HOUR WHERE activity_id=%s",
        aid,
    )


def test_signup_toggle(api):
    payload = {"email": "new@elio.test", "displayName": "New", "password": "NewPassword@2026"}
    assert api.get("/api/v1/auth/options").json() == {"selfRegistrationEnabled": False}
    assert api.post("/api/v1/auth/sign-up", json=payload).status_code == 403
    api.app.state.settings.self_registration_enabled = True
    assert api.post("/api/v1/auth/sign-up", json=payload).status_code == 201
    assert api.post("/api/v1/auth/sign-up", json=payload).status_code == 409


def test_team_reason_without_version_or_password(api):
    c = class_with_student(api)
    co = create_user(api, c.admin, "co@elio.test", "INSTRUCTOR")
    root = f"/api/v1/offerings/{c.offering_id}"
    assert co.account_id in [
        a["id"] for a in c.prof.get(root + "/teaching-team/candidates").json()["items"]
    ]
    added = c.prof.post(root + "/teaching-team", json={"accountId": co.account_id})
    assert added.status_code == 201, added.text
    transferred = c.prof.post(
        root + "/lead-transfer",
        json={"membershipId": added.json()["id"], "reason": "New coordinator"},
    )
    assert transferred.status_code == 200, transferred.text
    assert c.prof.post(root + "/teaching-team", json={"email": "co@elio.test"}).status_code == 403
    assert co.get(root).json()["permissions"]["manageTeam"]
    assert c.admin.get(root + "/resources").status_code == 404


def test_original_receipt_replay_and_changed_payload(api):
    c = class_with_student(api)
    box = _box(c)
    key = "confirmation-main-test-12345"
    fid = _upload(c.student, c, box["id"]).json()["id"]
    payload = {"expectedVersion": 0, "fileIds": [fid]}
    path = f"/api/v1/assignments/{box['id']}/submissions"
    assert c.student.client.post(path, json=payload, headers=c.student.headers()).status_code == 400
    response = c.student.client.post(
        path, json=payload, headers={**c.student.headers(), "Idempotency-Key": key}
    )
    assert response.status_code == 201, response.text
    first = response.json()["currentVersion"]
    second = _upload(c.student, c, box["id"]).json()["id"]
    assert _submit(c.student, box["id"], [second], expected=1).status_code == 201
    assert (
        c.student.client.post(
            path, json=payload, headers={**c.student.headers(), "Idempotency-Key": key}
        ).json()["currentVersion"]
        == first
    )
    assert (
        c.student.get(f"/api/v1/assignments/{box['id']}/submission-receipts/{key}").json() == first
    )
    conflict = c.student.client.post(
        path,
        json={**payload, "fileIds": [second]},
        headers={**c.student.headers(), "Idempotency-Key": key},
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_grading_cutoff_zero_revision_and_publication(api):
    c = class_with_student(api)
    box = _box(c)
    fid = _upload(c.student, c, box["id"]).json()["id"]
    sid = _submit(c.student, box["id"], [fid]).json()["id"]
    payload = {"expectedSubmissionVersion": 1, "sourceVersionNo": 1, "score": 0}
    path = f"/api/v1/submissions/{sid}/grade-record"
    assert c.prof.post(path, json=payload).status_code == 409
    close_assignment(api, box["id"])
    response = c.prof.post(path, json=payload)
    assert response.status_code == 200, response.text
    grade = response.json()
    assert grade["draftRevision"]["grade"] == 0
    root = f"/api/v1/grade-records/{grade['id']}"
    assert c.student.get(root).status_code == 404
    published = c.prof.put(root + "/publication", json={"revisionNo": 1}, version=grade["version"])
    assert published.status_code == 200, published.text
    assert (
        c.prof.post(
            root + "/revisions", json={**payload, "score": 8}, version=published.json()["version"]
        ).status_code
        == 400
    )
    revised = c.prof.post(
        root + "/revisions",
        json={**payload, "score": 8, "reason": "Rechecked solution"},
        version=published.json()["version"],
    )
    assert revised.status_code == 201, revised.text
    assert revised.json()["draftRevision"]["grade"] == 8
    assert c.student.get(root).json()["publishedRevision"]["grade"] == 0
    assert (
        c.prof.put(
            root + "/publication", json={"revisionNo": 2}, version=published.json()["version"]
        ).status_code
        == 412
    )
    assert (
        c.prof.put(
            root + "/publication", json={"revisionNo": 2}, version=revised.json()["version"]
        ).status_code
        == 200
    )
    visible = c.student.get(root).json()
    assert visible["publishedRevision"]["grade"] == 8
    assert visible["publishedRevision"]["reason"] is None
    assert visible["current"]["reason"] is None and visible["released"]["reason"] is None
    assert c.prof.get(root).json()["publishedRevision"]["reason"] == "Rechecked solution"


def test_multiple_attempts_numeric_answer_version_and_release(api):
    c = class_with_student(api)
    quiz = _published(c, _true_false(True), maxAttempts=2, releasePolicy="IMMEDIATE")
    response = c.student.post(f"/api/v1/quizzes/{quiz['id']}/attempts")
    assert response.status_code == 201, response.text
    attempt = response.json()
    aid = attempt["id"]
    qid = attempt["questions"][0]["id"]
    path = f"/api/v1/quiz-attempts/{aid}/answers/{qid}"
    saved = c.student.put(path, json={"option": 1}, version=attempt["version"])
    assert saved.status_code == 200, saved.text
    assert c.student.put(path, json={"option": 2}, version=attempt["version"]).status_code == 412
    sealed = c.student.post(f"/api/v1/quiz-attempts/{aid}/seal", version=saved.json()["version"])
    assert sealed.status_code == 200, sealed.text
    result = c.student.get(f"/api/v1/quiz-attempts/{aid}/result")
    assert result.status_code == 200, result.text
    assert result.json()["score"] == 10 and result.json()["answersShown"] is False
    own = c.student.get(f"/api/v1/quizzes/{quiz['id']}/attempts/me").json()
    assert own["canStart"] and own["attemptsUsed"] == 1
    assert c.student.post(f"/api/v1/quizzes/{quiz['id']}/attempts").json()["attemptNo"] == 2


def test_personal_empty_views(api):
    c = class_with_student(api)
    progress = c.student.get("/api/v1/me/progress")
    assert progress.status_code == 200, progress.text
    assert progress.json()["rows"]["items"][0]["notice"] == "NO_MANDATORY_ACTIVITIES"
    dashboard = c.student.get("/api/v1/dashboard")
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["tasks"] == []
    calendar = c.student.get("/api/v1/me/calendar")
    assert calendar.status_code == 200, calendar.text
    assert calendar.json()["items"] == []


def test_group_formation_limit_and_frozen_single_roster(api):
    from tests.test_grading import _enroll_outsider

    c = class_with_student(api)
    _enroll_outsider(c)
    box = _box(c, mode="GROUP", maxGroupSize=2, groupFormation="INSTRUCTOR")
    url = f"/api/v1/assignments/{box['id']}/groups"
    assert c.student.post(url, json={"name": "Not allowed"}).status_code == 403
    group = c.prof.post(
        url, json={"name": "Assigned", "memberIds": [c.student.account_id, c.outsider.account_id]}
    )
    assert group.status_code == 201, group.text
    gid = group.json()["id"]
    fid = _upload(c.student, c, box["id"]).json()["id"]
    assert c.outsider.get(f"/api/v1/files/{fid}").status_code == 404
    first = c.student.client.post(
        f"/api/v1/assignments/{box['id']}/submissions",
        json={"expectedVersion": 0, "groupId": gid, "fileIds": [fid]},
        headers={**c.student.headers(), "Idempotency-Key": "group-first-confirmation-123"},
    )
    assert first.status_code == 201, first.text
    assert first.json()["recipientStudentIds"] == sorted(
        [c.student.account_id, c.outsider.account_id]
    )
    assert c.outsider.get(f"/api/v1/files/{fid}/content").status_code == 200
    before = c.student.get(f"/api/v1/groups/{gid}").json()
    assert before["locked"] and before["lockedAt"]
    assert "frozenRecipients" not in before
    assert (
        c.prof.patch(
            f"/api/v1/groups/{gid}", json={"memberIds": [c.student.account_id]}
        ).status_code
        == 409
    )
    second_file = _upload(c.outsider, c, box["id"]).json()["id"]
    stale = c.outsider.post(
        f"/api/v1/assignments/{box['id']}/submissions",
        json={"expectedVersion": 0, "groupId": gid, "fileIds": [second_file]},
    )
    assert stale.status_code == 412
    second = c.outsider.post(
        f"/api/v1/assignments/{box['id']}/submissions",
        json={"expectedVersion": 1, "groupId": gid, "fileIds": [second_file]},
    )
    assert second.status_code == 201, second.text
    assert c.student.get(f"/api/v1/assignments/{box['id']}/submissions/me").json()["version"] == 2


def test_missing_group_zero_freezes_without_receipt_and_stays_incomplete(api):
    from tests.test_grading import _enroll_outsider

    c = class_with_student(api)
    _enroll_outsider(c)
    box = _box(c, mode="GROUP", maxGroupSize=2, mandatory=True)
    group = c.prof.post(
        f"/api/v1/assignments/{box['id']}/groups",
        json={"name": "Team", "memberIds": [c.student.account_id, c.outsider.account_id]},
    ).json()
    close_assignment(api, box["id"])
    response = c.prof.post(
        f"/api/v1/assignments/{box['id']}/missing-work-decisions",
        json={"studentId": c.student.account_id, "zeroReason": "No submission by cutoff"},
    )
    assert response.status_code == 200, response.text
    record = response.json()
    assert record["draftRevision"]["grade"] == 0 and record["draftRevision"]["specialMark"] is None
    assert (
        c.prof.put(
            f"/api/v1/grade-records/{record['id']}/publication",
            json={"revisionNo": 1},
            version=record["version"],
        ).status_code
        == 200
    )
    for student in (c.student, c.outsider):
        stream = student.get(f"/api/v1/assignments/{box['id']}/submissions/me").json()
        assert stream["status"] == "NOT_SUBMITTED" and stream["currentVersion"] is None
        assert student.get(f"/api/v1/submissions/{stream['id']}/history").json()["history"] == []
        assert student.get("/api/v1/me/progress").json()["rows"]["items"][0]["completed"] == 0
    assert c.prof.get(f"/api/v1/groups/{group['id']}").json()["locked"]


def test_bank_snapshot_release_worker_and_notification_replay(api):
    from app.services.quiz_service import QuizService

    c = class_with_student(api)
    bank = f"/api/v1/offerings/{c.offering_id}/question-bank-items"
    question = {
        "type": "TRUE_FALSE",
        "text": "Original statement",
        "correctAnswer": True,
        "points": 4,
    }
    created = c.prof.post(bank, json=question)
    assert created.status_code == 201, created.text
    source = created.json()
    quiz = c.prof.post(
        f"/api/v1/offerings/{c.offering_id}/quizzes",
        json={
            "title": "Bank quiz",
            "openAt": _quiz_time(-5),
            "closeAt": _quiz_time(20),
            "durationMinutes": 1,
            "totalPoints": 4,
            "releasePolicy": "AFTER_CLOSE",
            "questions": [{"questionItemId": source["id"], "points": 4}],
        },
    ).json()
    assert c.prof.put(f"/api/v1/quizzes/{quiz['id']}/publication").status_code == 200
    assert (
        c.prof.patch(
            f"/api/v1/question-bank-items/{source['id']}",
            json={**question, "text": "Edited bank", "correctAnswer": False},
            version=source["version"],
        ).status_code
        == 200
    )
    assert len(c.prof.get(bank).json()["items"]) == 1
    attempt = c.student.post(f"/api/v1/quizzes/{quiz['id']}/attempts").json()
    assert attempt["questions"][0]["text"] == "Original statement"
    answer = c.student.put(
        f"/api/v1/quiz-attempts/{attempt['id']}/answers/{attempt['questions'][0]['id']}",
        json={"option": 1},
        version=attempt["version"],
    )
    assert answer.status_code == 200, answer.text
    sealed = c.student.post(
        f"/api/v1/quiz-attempts/{attempt['id']}/seal", version=answer.json()["version"]
    )
    assert sealed.status_code == 200, sealed.text
    hidden = c.student.get(f"/api/v1/quiz-attempts/{attempt['id']}/result").json()
    assert (
        hidden["state"] == "WAITING_FOR_CLOSE"
        and hidden["score"] is None
        and hidden["questions"] == []
    )
    _run_sql(
        api,
        "UPDATE quizzes SET open_at=UTC_TIMESTAMP(6)-INTERVAL 2 HOUR,close_at=UTC_TIMESTAMP(6)-INTERVAL 1 HOUR WHERE activity_id=%s",
        quiz["id"],
    )
    worker = QuizService(api.app.state.database)
    worker.finalize_expired_attempts()
    worker.finalize_expired_attempts()
    result = c.student.get(f"/api/v1/quiz-attempts/{attempt['id']}/result").json()
    assert result["state"] == "PUBLISHED" and result["score"] == 4
    notifications = c.student.get("/api/v1/me/notifications").json()["items"]
    assert sum(n["eventType"] == "QUIZ_RESULT_RELEASED" for n in notifications) == 1


def _quiz_time(minutes):
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) + timedelta(minutes=minutes)).isoformat()


def test_worker_corrupted_snapshot_is_error_not_zero(api):
    from app.services.quiz_service import QuizService

    c = class_with_student(api)
    quiz = _published(c, _true_false(True), releasePolicy="IMMEDIATE")
    attempt = c.student.post(f"/api/v1/quizzes/{quiz['id']}/attempts").json()
    _run_sql(
        api,
        "DELETE FROM quiz_snapshot_options WHERE quiz_question_id=%s",
        attempt["questions"][0]["id"],
    )
    _run_sql(
        api,
        "UPDATE quiz_attempts SET started_at=UTC_TIMESTAMP(6)-INTERVAL 3 HOUR,ends_at=UTC_TIMESTAMP(6)-INTERVAL 2 HOUR WHERE attempt_id=%s",
        attempt["id"],
    )
    QuizService(api.app.state.database).finalize_expired_attempts()
    response = c.student.get(f"/api/v1/quiz-attempts/{attempt['id']}/result")
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "GRADING_ERROR" and response.json()["score"] is None
    assert not response.json()["questions"]


def test_archived_locked_lead_can_be_repaired_without_password(api):
    c = class_with_student(api)
    co = create_user(api, c.admin, "replacement@elio.test", "INSTRUCTOR")
    root = f"/api/v1/offerings/{c.offering_id}"
    offering = c.prof.get(root).json()
    archived = c.prof.patch(root, json={"status": "ARCHIVED"}, version=offering["version"])
    assert archived.status_code == 200, archived.text
    account = next(
        a
        for a in c.admin.get("/api/v1/admin/accounts").json()["items"]
        if a["account"]["id"] == c.prof.account_id
    )
    assert (
        c.admin.patch(
            f"/api/v1/admin/accounts/{c.prof.account_id}",
            json={"status": "LOCKED", "reason": "Staff departure"},
            version=account["version"],
        ).status_code
        == 200
    )
    current = c.admin.get(root).json()
    assert current["permissions"]["repairLead"]
    assert (
        c.admin.post(
            root + "/restore", json={"reason": "Resume"}, version=current["version"]
        ).status_code
        == 409
    )
    member = c.admin.post(
        root + "/teaching-team", json={"accountId": co.account_id, "reason": "Replacement"}
    )
    assert member.status_code == 201, member.text
    moved = c.admin.post(
        root + "/lead-transfer",
        json={"membershipId": member.json()["id"], "reason": "Repair archived lead"},
    )
    assert moved.status_code == 200, moved.text
    current = c.admin.get(root).json()
    restored = c.admin.post(
        root + "/restore", json={"reason": "Resume"}, version=current["version"]
    )
    assert restored.status_code == 200, restored.text
    assert co.get(root).json()["permissions"]["manageTeam"]


def test_bank_points_are_json_numbers(api):
    c = class_with_student(api)
    question = c.prof.post(
        f"/api/v1/offerings/{c.offering_id}/question-bank-items",
        json={
            "type": "TRUE_FALSE",
            "text": "Numeric points",
            "correctAnswer": True,
            "points": 1.25,
        },
    )
    assert question.status_code == 201, question.text
    assert isinstance(question.json()["points"], (float, int))
    listing = c.prof.get(f"/api/v1/offerings/{c.offering_id}/question-bank-items")
    assert listing.json()["items"][0]["points"] == 1.25


def test_lock_races_lead_transfer_without_leaving_locked_open_lead(api):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    c = class_with_student(api)
    co = create_user(api, c.admin, "successor@elio.test", "INSTRUCTOR")
    root = f"/api/v1/offerings/{c.offering_id}"
    member = c.prof.post(root + "/teaching-team", json={"accountId": co.account_id}).json()
    account = next(
        a
        for a in c.admin.get("/api/v1/admin/accounts").json()["items"]
        if a["account"]["id"] == co.account_id
    )
    gate = Barrier(2)

    def transfer():
        gate.wait()
        return c.prof.post(
            root + "/lead-transfer",
            json={"membershipId": member["id"], "reason": "Concurrent coordinator change"},
        )

    def lock():
        gate.wait()
        return c.admin.patch(
            f"/api/v1/admin/accounts/{co.account_id}",
            json={"status": "LOCKED", "reason": "Concurrent account review"},
            version=account["version"],
        )

    with ThreadPoolExecutor(2) as pool:
        a, b = pool.submit(transfer), pool.submit(lock)
        responses = [a.result(), b.result()]
    assert all(r.status_code in {200, 409, 422} for r in responses), [r.text for r in responses]
    assert any(r.status_code in {409, 422} for r in responses)
    with api.app.state.database.read_connection() as connection:
        from app.infrastructure.db.sql import Sql

        assert (
            Sql(connection).scalar(
                "SELECT COUNT(*) FROM course_offerings o JOIN course_memberships m ON m.offering_id=o.offering_id JOIN users u ON u.user_id=m.user_id WHERE o.state IN ('DRAFT','OPEN') AND m.status='ACTIVE' AND m.course_role='PRIMARY_INSTRUCTOR' AND u.status='LOCKED'"
            )
            == 0
        )


def test_legacy_hidden_announcement_is_not_readable_or_counted_in_inbox(api):
    c = class_with_student(api)
    note = c.prof.post(
        f"/api/v1/offerings/{c.offering_id}/announcements",
        json={"title": "Visible title", "body": "Published body"},
    )
    assert note.status_code == 201, note.text
    assert c.student.get("/api/v1/me/notifications").json()["unreadCount"] == 1
    assert c.student.get("/api/v1/dashboard").json()["unread"] == 1
    _run_sql(
        api,
        "UPDATE announcements SET status='DRAFT',published_at=NULL WHERE announcement_id=%s",
        note.json()["id"],
    )
    assert c.student.get(f"/api/v1/announcements/{note.json()['id']}").status_code == 404
    assert c.student.get("/api/v1/me/notifications").json()["unreadCount"] == 0
    dashboard = c.student.get("/api/v1/dashboard").json()
    assert dashboard["unread"] == 0 and dashboard["announcements"] == []
