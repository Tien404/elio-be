"""Quizzes: points sharing, publish lock, attempts, automatic scoring, grade page."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain.entities import (
    GradingMethod,
    PublishStatus,
    Question,
    QuestionType,
    Quiz,
    QuizAttempt,
)
from tests.helpers import class_with_student


def _at(minutes):
    return (datetime.now(UTC) + timedelta(minutes=minutes)).isoformat()


def _quiz(c, **extra):
    body = {
        "title": "Quiz 1",
        "openAt": _at(-1),
        "closeAt": _at(120),
        "durationMinutes": 30,
        "totalPoints": 10,
        "releasePolicy": "IMMEDIATE",
        **extra,
    }
    response = c.prof.post(f"/api/v1/offerings/{c.offering_id}/quizzes", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _choice(text="2 + 2 = ?", correct=2, **extra):
    return {"type": "SINGLE_CHOICE", "text": text, "options": ["3", "4", "5"],
            "correctOption": correct, **extra}  # fmt: skip


def _true_false(answer=True, **extra):
    return {"type": "TRUE_FALSE", "text": "The sky is blue.", "correctAnswer": answer, **extra}


def _add(c, quiz_id, question):
    response = c.prof.post(f"/api/v1/quizzes/{quiz_id}/questions", json=question)
    assert response.status_code == 201, response.text
    return response.json()


def _points(view):
    return [(q["points"], q["customPoints"]) for q in view["questions"]]


def _published(c, *questions, **extra):
    quiz = _quiz(c, **extra)
    for question in questions:
        _add(c, quiz["id"], question)
    published = c.prof.put(f"/api/v1/quizzes/{quiz['id']}/publication")
    assert published.status_code == 200, published.text
    return published.json()


def _run_sql(api, statement, *params):
    with api.app.state.database.transaction() as connection:
        cursor = connection.cursor()
        cursor.execute(statement, params)
        cursor.close()


# ----------------------------------------------------------------- pure rules
def _entity(total=10, method="HIGHEST_SCORE", max_attempts=0):
    return Quiz(1, "Q", None, None, 10, Decimal(total), PublishStatus.DRAFT, Decimal(total),
                max_attempts, GradingMethod(method))  # fmt: skip


def test_points_are_shared_with_leftover_on_last_question():
    quiz = _entity()
    assert quiz.distribute_points([None, None, None]) == [
        Decimal("3.33"), Decimal("3.33"), Decimal("3.34")]  # fmt: skip
    assert quiz.distribute_points([Decimal(5), None, None]) == [5, Decimal("2.5"), Decimal("2.5")]
    assert quiz.max_score == 10
    quiz.distribute_points([Decimal(4), Decimal(8)])
    assert quiz.max_score == 12  # every question set by hand: the total becomes their sum
    for custom in ([Decimal(11), None], [Decimal(10), None]):
        with pytest.raises(ValueError):
            quiz.distribute_points(custom)


@pytest.mark.parametrize(
    "method,expected",
    [("HIGHEST_SCORE", Decimal(8)), ("LATEST_ATTEMPT", Decimal(3)), ("AVERAGE", Decimal("5.67"))],
)
def test_counted_score_follows_the_grading_method(method, expected):
    quiz = _entity(method=method)
    assert quiz.counted_score([Decimal(6), Decimal(8), Decimal(3)]) == expected
    assert quiz.counted_score([]) is None
    assert quiz.can_start(99)  # 0 = unlimited
    assert not _entity(max_attempts=2).can_start(2)


def test_publish_and_is_open():
    quiz = _entity()
    now = datetime.now(UTC)
    quiz.open_at, quiz.close_at = now - timedelta(minutes=1), now + timedelta(minutes=30)
    assert not quiz.is_open(now)  # still a draft
    quiz.publish()
    assert quiz.is_open(now) and not quiz.is_open(quiz.close_at)
    with pytest.raises(ValueError):
        quiz.publish()


def test_attempt_is_graded_from_correct_answers():
    questions = [
        Question(1, "2 + 2", QuestionType.SINGLE_CHOICE, ["3", "4"], 2, Decimal(5)),
        Question(2, "Sky is blue", QuestionType.TRUE_FALSE, ["True", "False"], 1, Decimal(3)),
        Question(3, "Unanswered", QuestionType.TRUE_FALSE, ["True", "False"], 1, Decimal(2)),
    ]
    now = datetime.now(UTC)
    attempt = QuizAttempt(1, now, now + timedelta(minutes=10))
    attempt.save_answer(1, 2)
    attempt.save_answer(2, 2)
    assert not attempt.has_expired(now) and attempt.has_expired(now + timedelta(minutes=10))
    attempt.finish(now)
    assert attempt.grade(questions) == 5 and attempt.score == 5
    with pytest.raises(ValueError):
        attempt.save_answer(3, 1)  # submitted: no more answers


# --------------------------------------------------------------- professor
def test_professor_builds_quiz_and_points_rebalance(api):
    c = class_with_student(api)
    quiz = _quiz(c)
    assert quiz["status"] == "DRAFT" and quiz["maxAttempts"] == 1
    assert quiz["gradingMethod"] == "HIGHEST_SCORE"
    for _ in range(3):
        view = _add(c, quiz["id"], _choice())
    assert _points(view) == [(3.33, False), (3.33, False), (3.34, False)]

    first = view["questions"][0]["id"]
    url = f"/api/v1/quizzes/{quiz['id']}/questions/{first}"
    view = c.prof.put(url, json=_choice(points=5)).json()
    assert _points(view) == [(5, True), (2.5, False), (2.5, False)]

    too_much = c.prof.post(f"/api/v1/quizzes/{quiz['id']}/questions", json=_choice(points=20))
    assert too_much.status_code == 422 and too_much.json()["code"] == "INVALID_POINTS"

    view = c.prof.put(url, json=_choice()).json()  # no points: back to an equal share
    assert _points(view)[0] == (3.33, False)
    view = c.prof.delete(url).json()
    assert _points(view) == [(5, False), (5, False)] and view["questionCount"] == 2
    assert [q["position"] for q in view["questions"]] == [1, 2]

    changed = c.prof.patch(
        f"/api/v1/quizzes/{quiz['id']}",
        json={"totalPoints": 20, "maxAttempts": 0, "gradingMethod": "AVERAGE"},
        version=view["version"],
    )
    assert changed.status_code == 200, changed.text
    assert _points(changed.json()) == [(10, False), (10, False)]


def test_total_comes_back_when_a_shared_question_is_added(api):
    c = class_with_student(api)
    quiz = _quiz(c)  # total 10
    only = _add(c, quiz["id"], _choice(points=4))
    assert only["totalPoints"] == 4  # every question set by hand: total = their sum
    both = _add(c, quiz["id"], _true_false())
    assert both["totalPoints"] == 10 and _points(both) == [(4, True), (6, False)]


def test_publish_freezes_the_quiz(api):
    c = class_with_student(api)
    quiz = _quiz(c)
    empty = c.prof.put(f"/api/v1/quizzes/{quiz['id']}/publication")
    assert empty.status_code == 409 and empty.json()["code"] == "QUIZ_EMPTY"
    assert c.student.get(f"/api/v1/quizzes/{quiz['id']}").status_code == 404  # draft hidden

    _add(c, quiz["id"], _choice())
    published = c.prof.put(f"/api/v1/quizzes/{quiz['id']}/publication").json()
    assert published["status"] == "PUBLISHED"
    locked = c.prof.post(f"/api/v1/quizzes/{quiz['id']}/questions", json=_choice())
    assert locked.status_code == 409 and locked.json()["code"] == "QUIZ_LOCKED"
    patch = c.prof.patch(
        f"/api/v1/quizzes/{quiz['id']}", json={"title": "x"}, version=published["version"]
    )
    assert patch.status_code == 409

    student_view = c.student.get(f"/api/v1/quizzes/{quiz['id']}").json()
    assert student_view["questions"] is None  # students never get the answer key
    listed = c.student.get(f"/api/v1/offerings/{c.offering_id}/quizzes").json()
    assert [q["id"] for q in listed["items"]] == [quiz["id"]]


def test_quiz_input_rules(api):
    c = class_with_student(api)
    url = f"/api/v1/offerings/{c.offering_id}/quizzes"
    base = {"title": "Q", "openAt": _at(0), "closeAt": _at(20), "totalPoints": 10}
    assert c.prof.post(url, json={**base, "durationMinutes": 30}).status_code == 400
    assert c.student.post(url, json={**base, "durationMinutes": 10}).status_code == 403
    assert c.outsider.post(url, json={**base, "durationMinutes": 10}).status_code == 404

    quiz = _quiz(c)
    add = f"/api/v1/quizzes/{quiz['id']}/questions"
    assert c.prof.post(add, json=_choice(correct=4)).status_code == 400  # only 3 options
    assert c.prof.post(add, json=_true_false(options=["a", "b"])).status_code == 400
    assert c.prof.post(add, json={"type": "SINGLE_CHOICE", "text": "x"}).status_code == 400


# ----------------------------------------------------------------- student
def test_student_takes_quiz_and_is_scored(api):
    c = class_with_student(api)
    quiz = _published(c, _choice(points=5), _true_false())
    attempt = c.student.post(f"/api/v1/quizzes/{quiz['id']}/attempts")
    assert attempt.status_code == 201, attempt.text
    attempt = attempt.json()
    assert attempt["status"] == "IN_PROGRESS" and attempt["attemptNo"] == 1
    choice, true_false = attempt["questions"]
    assert [o["number"] for o in choice["options"]] == [1, 2, 3]
    assert [(o["number"], o["text"]) for o in true_false["options"]] == [(1, "True"), (2, "False")]
    assert "correctOption" not in choice and "correctOption" not in choice

    # resuming returns the same attempt
    again = c.student.post(f"/api/v1/quizzes/{quiz['id']}/attempts").json()
    assert again["id"] == attempt["id"]

    answer = f"/api/v1/quiz-attempts/{attempt['id']}/answers"
    assert (
        c.student.put(
            f"{answer}/{choice['id']}",
            json={"option": 4},
            version=c.student.get(
                (f"{answer}/{choice['id']}").split("/answers")[0].removesuffix("/seal")
            )
            .json()
            .get("version", 1),
        ).status_code
        == 422
    )
    assert (
        c.student.put(
            f"{answer}/{choice['id']}",
            json={"option": 1},
            version=c.student.get(
                (f"{answer}/{choice['id']}").split("/answers")[0].removesuffix("/seal")
            )
            .json()
            .get("version", 1),
        ).status_code
        == 200
    )
    assert (
        c.student.put(
            f"{answer}/{choice['id']}",
            json={"option": 2},
            version=c.student.get(
                (f"{answer}/{choice['id']}").split("/answers")[0].removesuffix("/seal")
            )
            .json()
            .get("version", 1),
        ).status_code
        == 200
    )
    c.student.put(
        f"{answer}/{true_false['id']}",
        json={"option": 2},
        version=c.student.get(
            (f"{answer}/{true_false['id']}").split("/answers")[0].removesuffix("/seal")
        )
        .json()
        .get("version", 1),
    )
    shown = c.student.get(f"/api/v1/quiz-attempts/{attempt['id']}").json()
    assert [q["selectedOption"] for q in shown["questions"]] == [2, 2]

    sealed = c.student.post(
        f"/api/v1/quiz-attempts/{attempt['id']}/seal",
        version=c.student.get(
            (f"/api/v1/quiz-attempts/{attempt['id']}/seal")
            .split("/answers")[0]
            .removesuffix("/seal")
        )
        .json()
        .get("version", 1),
    )
    assert sealed.status_code == 200 and sealed.json()["score"] == 5  # only the first is right
    assert sealed.json()["finishedBy"] == "STUDENT"
    late = c.student.put(
        f"{answer}/{choice['id']}",
        json={"option": 1},
        version=c.student.get(
            (f"{answer}/{choice['id']}").split("/answers")[0].removesuffix("/seal")
        )
        .json()
        .get("version", 1),
    )
    assert late.status_code == 409 and late.json()["code"] == "ATTEMPT_FINISHED"

    result = c.student.get(f"/api/v1/quiz-attempts/{attempt['id']}/result").json()
    assert result["score"] == 5 and result["percentage"] == 50
    assert result["answersShown"] is False  # not before the quiz closes
    assert all(q["correct"] is None and q["correctOption"] is None for q in result["questions"])
    teacher = c.prof.get(f"/api/v1/quiz-attempts/{attempt['id']}/result").json()
    assert [q["correct"] for q in teacher["questions"]] == [True, False]

    no_more = c.student.post(f"/api/v1/quizzes/{quiz['id']}/attempts")
    assert no_more.status_code == 409 and no_more.json()["code"] == "NO_ATTEMPTS_LEFT"

    row = next(i for i in c.student.get("/api/v1/me/grades").json()["items"][0]["items"])
    assert row["type"] == "QUIZ" and row["activityId"] == quiz["id"]
    assert row["grade"] == 5 and row["percentage"] == 50 and row["status"] == "RELEASED"


def test_several_attempts_and_counted_score(api):
    c = class_with_student(api)
    quiz = _published(c, _true_false(), maxAttempts=0, gradingMethod="AVERAGE")
    for option in (1, 2, 2):  # True (right), False, False: 10, 0, 0 points
        attempt = c.student.post(f"/api/v1/quizzes/{quiz['id']}/attempts").json()
        question = attempt["questions"][0]["id"]
        c.student.put(
            f"/api/v1/quiz-attempts/{attempt['id']}/answers/{question}",
            json={"option": option},
            version=c.student.get(
                (f"/api/v1/quiz-attempts/{attempt['id']}/answers/{question}")
                .split("/answers")[0]
                .removesuffix("/seal")
            )
            .json()
            .get("version", 1),
        )
        c.student.post(
            f"/api/v1/quiz-attempts/{attempt['id']}/seal",
            version=c.student.get(
                (f"/api/v1/quiz-attempts/{attempt['id']}/seal")
                .split("/answers")[0]
                .removesuffix("/seal")
            )
            .json()
            .get("version", 1),
        )
    mine = c.student.get(f"/api/v1/quizzes/{quiz['id']}/attempts/me").json()
    assert mine["attemptsUsed"] == 3 and mine["canStart"] is True  # unlimited
    assert [a["score"] for a in mine["attempts"]] == [10, 0, 0]
    assert mine["countedScore"] == 3.33


def test_time_running_out_submits_the_attempt(api):
    c = class_with_student(api)
    quiz = _published(c, _true_false())
    attempt = c.student.post(f"/api/v1/quizzes/{quiz['id']}/attempts").json()
    question = attempt["questions"][0]["id"]
    c.student.put(
        f"/api/v1/quiz-attempts/{attempt['id']}/answers/{question}",
        json={"option": 1},
        version=c.student.get(
            (f"/api/v1/quiz-attempts/{attempt['id']}/answers/{question}")
            .split("/answers")[0]
            .removesuffix("/seal")
        )
        .json()
        .get("version", 1),
    )
    _run_sql(
        api,
        """UPDATE quiz_attempts SET started_at = DATE_ADD(UTC_TIMESTAMP(6), INTERVAL -40 MINUTE),
               ends_at = DATE_ADD(UTC_TIMESTAMP(6), INTERVAL -10 MINUTE) WHERE attempt_id = %s""",
        attempt["id"],
    )
    after = c.student.get(f"/api/v1/quiz-attempts/{attempt['id']}").json()
    assert after["status"] == "FINISHED" and after["finishedBy"] == "SYSTEM"
    assert after["score"] == 10  # saved answers still count
    late = c.student.put(
        f"/api/v1/quiz-attempts/{attempt['id']}/answers/{question}",
        json={"option": 2},
        version=c.student.get(
            (f"/api/v1/quiz-attempts/{attempt['id']}/answers/{question}")
            .split("/answers")[0]
            .removesuffix("/seal")
        )
        .json()
        .get("version", 1),
    )
    assert late.status_code == 409


def test_answers_are_shown_after_the_quiz_closes(api):
    c = class_with_student(api)
    quiz = _published(c, _true_false(), _choice())
    attempt = c.student.post(f"/api/v1/quizzes/{quiz['id']}/attempts").json()
    c.student.post(
        f"/api/v1/quiz-attempts/{attempt['id']}/seal",
        version=c.student.get(
            (f"/api/v1/quiz-attempts/{attempt['id']}/seal")
            .split("/answers")[0]
            .removesuffix("/seal")
        )
        .json()
        .get("version", 1),
    )
    _run_sql(
        api,
        """UPDATE quizzes SET open_at = DATE_ADD(UTC_TIMESTAMP(6), INTERVAL -3 HOUR),
               close_at = DATE_ADD(UTC_TIMESTAMP(6), INTERVAL -1 HOUR) WHERE activity_id = %s""",
        quiz["id"],
    )
    result = c.student.get(f"/api/v1/quiz-attempts/{attempt['id']}/result").json()
    assert result["answersShown"] is True and result["score"] == 0  # nothing answered
    assert [q["correctOption"] for q in result["questions"]] == [1, 2]
    closed = c.student.post(f"/api/v1/quizzes/{quiz['id']}/attempts")
    assert closed.status_code == 409 and closed.json()["code"] == "QUIZ_CLOSED"


def test_who_can_take_and_see_attempts(api):
    c = class_with_student(api)
    later = _published(c, _true_false(), openAt=_at(60), closeAt=_at(180))
    not_open = c.student.post(f"/api/v1/quizzes/{later['id']}/attempts")
    assert not_open.status_code == 409 and not_open.json()["code"] == "QUIZ_NOT_OPEN"

    quiz = _published(c, _true_false(), title="Quiz 2")
    assert c.prof.post(f"/api/v1/quizzes/{quiz['id']}/attempts").status_code == 403
    assert c.outsider.post(f"/api/v1/quizzes/{quiz['id']}/attempts").status_code == 404
    attempt = c.student.post(f"/api/v1/quizzes/{quiz['id']}/attempts").json()
    assert c.outsider.get(f"/api/v1/quiz-attempts/{attempt['id']}").status_code == 404
    assert c.prof.get(f"/api/v1/quiz-attempts/{attempt['id']}").status_code == 200
    unfinished = c.student.get(f"/api/v1/quiz-attempts/{attempt['id']}/result")
    assert unfinished.status_code == 409
    foreign = c.prof.put(
        f"/api/v1/quiz-attempts/{attempt['id']}/answers/{attempt['questions'][0]['id']}",
        json={"option": 1},
        version=c.prof.get(
            (f"/api/v1/quiz-attempts/{attempt['id']}/answers/{attempt['questions'][0]['id']}")
            .split("/answers")[0]
            .removesuffix("/seal")
        )
        .json()
        .get("version", 1),
    )
    assert foreign.status_code == 404
