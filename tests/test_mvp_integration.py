from datetime import UTC, datetime, timedelta

from tests.helpers import bootstrap_admin, class_with_student, create_user, login, temp_password


def test_session_reload_including_temporary_password(api):
    admin = bootstrap_admin(api)
    response = admin.post(
        "/api/v1/admin/accounts",
        json={
            "email": "first@elio.test",
            "displayName": "First",
            "role": "STUDENT",
            "canCreateCourse": False,
        },
    )
    account = response.json()["account"]["id"]
    first = login(api, "first@elio.test", temp_password(api, account))
    restored = first.get("/api/v1/auth/session")
    assert restored.status_code == 200
    assert restored.json()["session"]["restricted"] is True
    assert restored.json()["session"]["csrfToken"] == first.csrf
    assert first.get("/api/v1/me").status_code == 403


def test_join_code_lifecycle_restore_and_current_file_access(api):
    c = class_with_student(api)
    url = f"/api/v1/offerings/{c.offering_id}"
    current = c.prof.get(url).json()
    rotated = c.prof.patch(url, json={"joinCodeAction": "rotate"}, version=current["version"])
    assert rotated.status_code == 200, rotated.text
    oldcode = rotated.json()["joinCode"]
    joined = c.outsider.post("/api/v1/offerings/join", json={"code": oldcode})
    assert joined.status_code == 201, joined.text
    assert (
        c.outsider.post("/api/v1/offerings/join", json={"code": oldcode}).json()["id"]
        == joined.json()["id"]
    )
    topic = c.prof.post(f"{url}/topics", json={"title": "Week 1"}).json()
    text = c.prof.post(
        f"{url}/resources",
        json={
            "title": "Read",
            "topicId": topic["id"],
            "kind": "TEXT",
            "body": "Course content",
            "mandatory": True,
            "status": "PUBLISHED",
        },
    )
    assert text.status_code == 201, text.text
    rid = text.json()["id"]
    assert c.student.put(f"/api/v1/resources/{rid}/completion").json()["completed"] is True
    assert c.student.delete(f"/api/v1/resources/{rid}/completion").status_code == 204
    assert c.student.get(f"/api/v1/resources/{rid}").json()["completed"] is False
    changed = c.prof.patch(
        f"/api/v1/topics/{topic['id']}",
        json={"title": "Renamed", "position": 1},
        version=topic["version"],
    )
    assert changed.status_code == 200, changed.text
    archived = c.prof.patch(url, json={"status": "ARCHIVED"}, version=rotated.json()["version"])
    assert archived.status_code == 200, archived.text
    assert c.student.get(f"/api/v1/resources/{rid}").status_code == 200
    assert c.student.put(f"/api/v1/resources/{rid}/completion").status_code == 409
    assert c.prof.post(f"{url}/topics", json={"title": "Denied"}).status_code == 409
    restored = c.prof.post(
        f"{url}/restore", json={"reason": "Resume term"}, version=archived.json()["version"]
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["status"] == "OPEN"
    assert c.student.get("/api/v1/dashboard").status_code == 200


def test_cutoff_attachments_co_instructor_and_removed_owner(api):
    c = class_with_student(api)
    co = create_user(api, c.admin, "co@elio.test", "INSTRUCTOR")
    with api.app.state.database.transaction() as connection:
        connection.cursor().execute(
            "INSERT dbo.course_memberships (offering_id,user_id,course_role) VALUES (?,?,'CO_INSTRUCTOR')",
            c.offering_id,
            co.account_id,
        ).close()
    url = f"/api/v1/offerings/{c.offering_id}"
    team = co.get(f"{url}/teaching-team")
    assert team.status_code == 200 and len(team.json()["items"]) == 2
    attachment = co.post(
        "/api/v1/files",
        params={"offeringId": c.offering_id, "purpose": "ASSIGNMENT_ATTACHMENT"},
        files={"file": ("instructions.txt", b"Instructions", "text/plain")},
    )
    assert attachment.status_code == 201, attachment.text
    now = datetime.now(UTC)
    assignment = co.post(
        f"{url}/assignments",
        json={
            "title": "Work",
            "status": "PUBLISHED",
            "openAt": (now - timedelta(days=1)).isoformat(),
            "dueAt": (now + timedelta(days=1)).isoformat(),
            "cutoffAt": (now + timedelta(days=2)).isoformat(),
            "maxScore": 10,
            "weight": 25,
            "fileIds": [attachment.json()["id"]],
        },
    )
    assert assignment.status_code == 201, assignment.text
    box = assignment.json()
    aid = box["id"]
    assert box["cutoffAt"] and box["weight"] == 25 and len(box["attachments"]) == 1
    uploaded = c.student.post(
        "/api/v1/files",
        params={"offeringId": c.offering_id, "purpose": "SUBMISSION", "assignmentId": aid},
        files={"file": ("answer.txt", b"Answer", "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text
    file_id = uploaded.json()["id"]
    confirmed = c.student.post(
        f"/api/v1/assignments/{aid}/submissions", json={"expectedVersion": 0, "fileIds": [file_id]}
    )
    assert confirmed.status_code == 201, confirmed.text
    sid = confirmed.json()["id"]
    assert co.get(f"/api/v1/submissions/{sid}/history").status_code == 200
    with api.app.state.database.transaction() as connection:
        connection.cursor().execute(
            "UPDATE dbo.assignments SET open_at=DATEADD(DAY,-3,SYSUTCDATETIME()),due_at=DATEADD(DAY,-2,SYSUTCDATETIME()),cutoff_at=DATEADD(DAY,-1,SYSUTCDATETIME()) WHERE activity_id=?",
            aid,
        ).close()
    closed = c.student.post(
        "/api/v1/files",
        params={"offeringId": c.offering_id, "purpose": "SUBMISSION", "assignmentId": aid},
        files={"file": ("late.txt", b"Late", "text/plain")},
    )
    assert closed.status_code == 409, closed.text
    with api.app.state.database.transaction() as connection:
        connection.cursor().execute(
            "UPDATE dbo.course_memberships SET status='REMOVED' WHERE offering_id=? AND user_id=?",
            c.offering_id,
            c.student.account_id,
        ).close()
    assert c.student.get(f"/api/v1/submissions/{sid}").status_code == 404
    assert c.student.get(f"/api/v1/files/{file_id}/content").status_code == 404
