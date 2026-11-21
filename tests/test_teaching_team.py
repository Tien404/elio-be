"""Teaching team: add a co-instructor, hand the class over, remove / leave."""

from tests.helpers import class_with_student, create_user


def _team(c):
    url = f"/api/v1/offerings/{c.offering_id}/teaching-team"
    return {m["account"]["displayName"]: m for m in c.prof.get(url).json()["items"]}


def _add(user, c, email):
    return user.post(
        f"/api/v1/offerings/{c.offering_id}/teaching-team",
        json={"email": email, "reason": "Teaching assignment"},
    )


def _remove(user, c, membership_id):
    return user.patch(
        f"/api/v1/offerings/{c.offering_id}/memberships/{membership_id}",
        json={"status": "REMOVED", "reason": "Teaching reassignment"},
    )


def test_lead_adds_a_co_instructor_who_can_teach(api):
    c = class_with_student(api)
    co = create_user(api, c.admin, "co@elio.test", "INSTRUCTOR", name="Co")
    added = _add(c.prof, c, "CO@elio.test")
    assert added.status_code == 201, added.text
    assert added.json()["teachingRole"] == "CO_INSTRUCTOR" and added.json()["status"] == "ACTIVE"
    assert set(_team(c)) == {"Prof", "Co"}

    topic = co.post(f"/api/v1/offerings/{c.offering_id}/topics", json={"title": "Week 2"})
    assert topic.status_code == 201  # co-instructors can teach

    assert _add(co, c, "co@elio.test").status_code == 403  # only the lead manages the team
    again = _add(c.prof, c, "co@elio.test")
    assert again.status_code == 409 and again.json()["code"] == "ALREADY_MEMBER"
    for email in ("stu@elio.test", "nobody@elio.test"):
        wrong = _add(c.prof, c, email)
        assert wrong.status_code == 422 and wrong.json()["code"] == "INSTRUCTOR_NOT_FOUND"
    assert _add(c.student, c, "co@elio.test").status_code == 403


def test_hand_the_class_over(api):
    c = class_with_student(api)
    co = create_user(api, c.admin, "co@elio.test", "INSTRUCTOR", name="Co")
    membership = _add(c.prof, c, "co@elio.test").json()
    url = f"/api/v1/offerings/{c.offering_id}/lead-transfer"

    lead_row = _team(c)["Prof"]["id"]
    not_co = c.prof.post(
        url, json={"reason": "Teaching reassignment", "membershipId": lead_row}
    )  # already the lead
    assert not_co.status_code == 422 and not_co.json()["code"] == "NOT_A_CO_INSTRUCTOR"

    moved = c.prof.post(
        url, json={"reason": "Teaching reassignment", "membershipId": membership["id"]}
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["teachingRole"] == "LEAD"
    team = _team(c)
    assert team["Co"]["teachingRole"] == "LEAD" and team["Prof"]["teachingRole"] == "CO_INSTRUCTOR"

    other = create_user(api, c.admin, "other@elio.test", "INSTRUCTOR", name="Other")
    assert _add(c.prof, c, "other@elio.test").status_code == 403  # no longer the lead
    assert _add(co, c, "other@elio.test").status_code == 201
    assert other.account_id


def test_remove_and_leave(api):
    c = class_with_student(api)
    co = create_user(api, c.admin, "co@elio.test", "INSTRUCTOR", name="Co")
    membership = _add(c.prof, c, "co@elio.test").json()
    lead_id = _team(c)["Prof"]["id"]

    lead = _remove(c.prof, c, lead_id)
    assert lead.status_code == 409 and lead.json()["code"] == "LEAD_CANNOT_BE_REMOVED"
    assert _remove(c.student, c, membership["id"]).status_code == 403

    left = _remove(co, c, membership["id"])  # a co-instructor may leave
    assert left.status_code == 200 and left.json()["status"] == "REMOVED"
    assert co.get(f"/api/v1/offerings/{c.offering_id}").status_code == 404
    assert set(_team(c)) == {"Prof"}
    twice = _remove(c.prof, c, membership["id"])
    assert twice.status_code == 409 and twice.json()["code"] == "NOT_A_CO_INSTRUCTOR"

    back = _add(c.admin, c, "co@elio.test")  # admins can help too
    assert back.status_code == 201 and back.json()["id"] == membership["id"]  # same membership
    assert back.json()["status"] == "ACTIVE"
    wrong_class = c.prof.patch(
        f"/api/v1/offerings/{c.offering_id + 999}/memberships/{membership['id']}",
        json={"status": "REMOVED", "reason": "Teaching reassignment"},
    )
    assert wrong_class.status_code == 404
