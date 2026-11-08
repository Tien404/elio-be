"""MVP step 5: ContentService — topics, file/link materials, private downloads."""

import hashlib

import pytest

from app.services import content_service
from tests.helpers import class_with_student

PDF = b"%PDF-1.4 week one slides"


def _topic(prof, oid, title="Week 1", **extra):
    response = prof.post(f"/api/v1/offerings/{oid}/topics", json={"title": title, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def _upload(user, oid, data=PDF, name="week1.pdf", mime="application/pdf"):
    return user.post(
        "/api/v1/files",
        params={"offeringId": oid, "purpose": "MATERIAL"},
        files={"file": (name, data, mime)},
    )


def _file_material(prof, oid, topic_id, file_id, status="DRAFT", title="Week 1 slides"):
    return prof.post(
        f"/api/v1/offerings/{oid}/resources",
        json={
            "title": title,
            "topicId": topic_id,
            "kind": "FILE",
            "status": status,
            "fileIds": [file_id],
        },
    )


def test_topics_get_next_position(api):
    c = class_with_student(api)
    oid = c.offering_id
    assert _topic(c.prof, oid)["position"] == 1
    assert _topic(c.prof, oid, "Week 2")["position"] == 2
    taken = c.prof.post(f"/api/v1/offerings/{oid}/topics", json={"title": "X", "position": 1})
    assert taken.status_code == 409 and taken.json()["code"] == "POSITION_TAKEN"
    titles = [t["title"] for t in c.student.get(f"/api/v1/offerings/{oid}/topics").json()["items"]]
    assert titles == ["Week 1", "Week 2"]


def test_upload_publish_and_download_file_material(api):
    c = class_with_student(api)
    oid = c.offering_id
    topic = _topic(c.prof, oid)

    uploaded = _upload(c.prof, oid)
    assert uploaded.status_code == 201, uploaded.text
    file = uploaded.json()
    assert file["state"] == "STAGING" and file["byteSize"] == len(PDF)
    assert file["sha256"] == hashlib.sha256(PDF).hexdigest()
    assert file["originalName"] == "week1.pdf"

    created = _file_material(c.prof, oid, topic["id"], file["id"])
    assert created.status_code == 201, created.text
    material = created.json()
    assert material["kind"] == "FILE" and material["fileIds"] == [file["id"]]
    assert material["status"] == "DRAFT" and material["version"] == 1

    # drafts are invisible to students
    resources = f"/api/v1/offerings/{oid}/resources"
    assert c.student.get(resources).json()["items"] == []
    assert c.student.get(f"/api/v1/resources/{material['id']}").status_code == 404
    assert c.student.get(f"/api/v1/files/{file['id']}/content").status_code == 404
    assert len(c.prof.get(resources).json()["items"]) == 1

    # publish (needs the current version)
    url = f"/api/v1/resources/{material['id']}"
    stale = c.prof.patch(url, json={"status": "PUBLISHED"}, version=2)
    assert stale.status_code == 412
    published = c.prof.patch(url, json={"status": "PUBLISHED"}, version=1)
    assert published.status_code == 200 and published.json()["status"] == "PUBLISHED"
    assert published.headers["etag"] == '"2"'

    assert [m["id"] for m in c.student.get(resources).json()["items"]] == [material["id"]]
    download = c.student.get(f"/api/v1/files/{file['id']}/content")
    assert download.status_code == 200 and download.content == PDF
    assert download.headers["content-disposition"].startswith("attachment")
    assert "week1.pdf" in download.headers["content-disposition"]
    assert download.headers["x-content-type-options"] == "nosniff"


def test_link_material_and_input_rules(api):
    c = class_with_student(api)
    oid = c.offering_id
    topic = _topic(c.prof, oid)
    resources = f"/api/v1/offerings/{oid}/resources"
    link = {
        "title": "Python docs",
        "topicId": topic["id"],
        "kind": "LINK",
        "status": "PUBLISHED",
        "externalUrl": "https://docs.python.org/3/",
    }
    created = c.prof.post(resources, json=link)
    assert created.status_code == 201, created.text
    assert created.json()["externalUrl"] == "https://docs.python.org/3/"
    assert created.json()["fileIds"] == []
    assert c.student.get(resources).json()["totalItems"] == 1

    for bad in ({"externalUrl": "javascript:alert(1)"}, {"externalUrl": None}):
        assert c.prof.post(resources, json={**link, **bad}).status_code in (400, 422)
    assert c.prof.post(resources, json={**link, "topicId": 999999}).status_code == 422

    # a staged file can be attached only once
    file_id = _upload(c.prof, oid).json()["id"]
    assert _file_material(c.prof, oid, topic["id"], file_id).status_code == 201
    again = _file_material(c.prof, oid, topic["id"], file_id)
    assert again.status_code == 422 and again.json()["code"] == "FILE_NOT_USABLE"


def test_only_the_class_professor_manages_and_only_members_see(api):
    c = class_with_student(api)
    oid = c.offering_id
    topic = _topic(c.prof, oid)

    assert c.student.post(f"/api/v1/offerings/{oid}/topics", json={"title": "x"}).status_code == 403
    assert _upload(c.student, oid).status_code == 403
    for user in (c.outsider, c.admin):
        assert user.get(f"/api/v1/offerings/{oid}/resources").status_code == 404
        assert user.get(f"/api/v1/offerings/{oid}/topics").status_code == 404
        assert _upload(user, oid).status_code == 404

    file_id = _upload(c.prof, oid).json()["id"]
    _file_material(c.prof, oid, topic["id"], file_id, status="PUBLISHED")
    assert c.outsider.get(f"/api/v1/files/{file_id}/content").status_code == 404
    assert c.admin.get(f"/api/v1/files/{file_id}/content").status_code == 404
    assert c.prof.get(f"/api/v1/files/{file_id}/content").status_code == 200


def test_upload_size_limits(api, monkeypatch):
    c = class_with_student(api)
    monkeypatch.setattr(content_service, "MAX_MATERIAL_BYTES", 10)
    too_big = _upload(c.prof, c.offering_id, data=b"x" * 11)
    assert too_big.status_code == 413 and too_big.json()["code"] == "FILE_TOO_LARGE"
    empty = _upload(c.prof, c.offering_id, data=b"")
    assert empty.status_code == 400 and empty.json()["code"] == "EMPTY_FILE"
    assert _upload(c.prof, c.offering_id, data=b"x" * 10).status_code == 201
    # nothing half-written is left behind
    stored = list((api.app.state.settings.private_files_dir / "files").rglob("*"))
    assert [p for p in stored if p.is_file() and p.suffix == ".part"] == []


@pytest.mark.parametrize(
    ("raw", "clean"),
    [("../../etc/passwd", "passwd"), ("C:\\Users\\a\\notes.docx", "notes.docx"), ("", "file")],
)
def test_uploaded_names_are_cleaned(raw, clean):
    assert content_service.clean_file_name(raw) == clean
