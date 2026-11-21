"""Quizzes with automatic grading (class diagram: QuizService, Quiz, Question, QuizAttempt).

Professor: create quiz (total points, time limit, attempts, which attempt counts) -> add
single-choice / true-false questions (points: equal share of the total unless set by
hand) -> publish (questions are frozen, points locked).
Student: start attempt -> save answers -> submit (seal) or the timer runs out -> score =
sum of points of correct answers, shown at once. Which answers were right is shown
after the quiz closes.
"""

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.core.errors import (
    ApiError,
    FeatureNotImplemented,
    conflict,
    not_found,
    version_conflict,
)
from app.domain.context import Actor
from app.domain.entities import (
    GradingMethod,
    PublishStatus,
    Question,
    QuestionType,
    Quiz,
    QuizAttempt,
)
from app.infrastructure.db.repositories.assessment_repository import AssessmentRepository
from app.infrastructure.db.repositories.audit_repository import AuditRepository
from app.infrastructure.db.repositories.content_repository import ContentRepository
from app.infrastructure.db.repositories.course_repository import CourseRepository
from app.infrastructure.db.repositories.quiz_repository import QuizRepository
from app.infrastructure.db.sql import Sql
from app.services.access import is_teacher, require_member, require_student, require_teacher

CENT = Decimal("0.01")
QUIZ_FIELDS = [
    "title",
    "topicId",
    "openAt",
    "closeAt",
    "durationMinutes",
    "totalPoints",
    "weight",
    "maxAttempts",
    "gradingMethod",
]


# ------------------------------------------------------- rows -> entities
def quiz_from_row(row: dict[str, Any]) -> Quiz:
    return Quiz(
        quiz_id=row["activity_id"],
        title=row["title"],
        open_at=row["open_at"],
        close_at=row["close_at"],
        duration_minutes=row["duration_min"],
        max_score=Decimal(row["max_score"]),
        status=PublishStatus(row["status"]),
        set_total=Decimal(row["set_total"]),
        max_attempts=row["max_attempts"],
        grading_method=GradingMethod(row["grading_method"]),
    )


def question_from_frozen(row: dict[str, Any]) -> Question:
    """A question as frozen at publish (option keys are the numbers 1, 2, ...)."""
    return Question(
        question_id=row["quiz_question_id"],
        text=row["prompt"],
        type=QuestionType(row["question_type"]),
        options=[o["option_text"] for o in row["options"]],
        correct_option=int(row["correct_key"]),
        points=Decimal(row["points"]),
    )


def _load_attempt(repo: QuizRepository, row: dict[str, Any]) -> QuizAttempt:
    return QuizAttempt(
        attempt_id=row["attempt_id"],
        started_at=row["started_at"],
        ends_at=row["ends_at"],
        answers={
            question_id: int(answer["selected_key"])
            for question_id, answer in repo.answers(row["attempt_id"]).items()
        },
        submitted_at=row["submitted_at"],
        score=row["score"],
    )


# ---------------------------------------------------------------- views
def _num(value) -> float | None:
    return None if value is None else float(Decimal(value).quantize(CENT, ROUND_HALF_UP))


def quiz_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["activity_id"],
        "offeringId": row["offering_id"],
        "topicId": row["topic_id"],
        "title": row["title"],
        "status": row["status"],
        "openAt": row["open_at"],
        "closeAt": row["close_at"],
        "durationMinutes": row["duration_min"],
        "totalPoints": _num(row["max_score"]),
        "weight": _num(row["weight_pct"]),
        "maxAttempts": row["max_attempts"],
        "gradingMethod": row["grading_method"],
        "questionCount": row["question_count"],
        "version": row["version"],
    }


def question_view(row: dict[str, Any]) -> dict[str, Any]:
    """The professor's view of a question, with the right answer."""
    single = row["question_type"] == "SINGLE_CHOICE"
    return {
        "id": row["question_id"],
        "position": row["position"],
        "type": row["question_type"],
        "text": row["question_text"],
        "options": [o["option_text"] for o in row["options"]] if single else None,
        "correctOption": next((o["option_no"] for o in row["options"] if o["is_correct"]), None)
        if single
        else None,
        "correctAnswer": None if single else bool(row["tf_correct_answer"]),
        "explanation": row["explanation"],
        "points": _num(row["points"]),
        "customPoints": bool(row["is_custom_points"]),
    }


def attempt_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["attempt_id"],
        "quizId": row["quiz_id"],
        "attemptNo": row["attempt_no"],
        "startedAt": row["started_at"],
        "endsAt": row["ends_at"],
        "submittedAt": row["submitted_at"],
        "finishedBy": row["finalized_by"],
        "status": "FINISHED" if row["finalized_by"] else "IN_PROGRESS",
        "score": _num(row["score"]),
    }


# ------------------------------------------------------ finishing attempts
def finish_expired(sql: Sql, *, offering_id=None, student_id=None) -> None:
    """Attempts whose time ran out are submitted by the system with the saved answers.
    Called before anything reads attempts, so no background job is needed."""
    repo = QuizRepository(sql)
    now = AssessmentRepository(sql).db_now()
    for attempt_id in repo.expired_unfinished(now, offering_id=offering_id, student_id=student_id):
        row = repo.get_attempt(attempt_id, lock=True)
        _finish(sql, row, by="SYSTEM", at=row["ends_at"])


def _finish(sql: Sql, row: dict[str, Any], *, by: str, at) -> None:
    """QuizAttempt.finish + QuizAttempt.grade, then store the result."""
    repo = QuizRepository(sql)
    attempt = _load_attempt(repo, row)
    attempt.finish(at)
    questions = [question_from_frozen(q) for q in repo.frozen_questions(row["quiz_id"])]
    score = attempt.grade(questions)
    repo.finish(attempt_id=attempt.attempt_id, by=by, at=at, score=score)


class QuizService:
    def __init__(self, database=None):
        self.database = database

    # ============================================================ professor
    def create_quiz(self, *, actor: Actor, offering_id: int, data: dict[str, Any]):
        with self.database.transaction() as connection:
            sql = Sql(connection)
            require_teacher(CourseRepository(sql), actor, offering_id)
            self._check_quiz(sql, offering_id, data)
            quiz_id = QuizRepository(sql).insert_quiz(offering_id=offering_id, data=data)
            AuditRepository(sql).record(
                actor_id=actor.user_id,
                action="QUIZ_CREATED",
                target_type="QUIZ",
                target_id=quiz_id,
            )
            return self._teacher_view(sql, quiz_id)

    def list_quizzes(self, *, actor: Actor, offering_id: int, page: int, page_size: int):
        with self.database.transaction() as connection:
            sql = Sql(connection)
            member = require_member(CourseRepository(sql), actor, offering_id)
            rows, total = QuizRepository(sql).list_quizzes(
                offering_id,
                published_only=not is_teacher(member),
                offset=(page - 1) * page_size,
                limit=page_size,
            )
            return {
                "items": [quiz_view(r) for r in rows],
                "page": page,
                "pageSize": page_size,
                "totalItems": total,
                "totalPages": (total + page_size - 1) // page_size,
            }

    def get_quiz(self, *, actor: Actor, quiz_id: int):
        """Professor: settings + questions with answers. Student: settings only."""
        with self.database.transaction() as connection:
            sql = Sql(connection)
            row, teacher = self._visible_quiz(sql, actor, quiz_id)
            if teacher:
                return self._teacher_view(sql, quiz_id)
            return {**quiz_view(row), "questions": None}

    def update_quiz(self, *, actor: Actor, quiz_id: int, expected_version: int, changes):
        with self.database.transaction() as connection:
            sql = Sql(connection)
            repo, row = self._draft_quiz(sql, actor, quiz_id)
            if row["version"] != expected_version:
                raise version_conflict(row["version"])
            view = quiz_view(row)
            data = {k: view[k] for k in QUIZ_FIELDS}
            data["openAt"], data["closeAt"] = row["open_at"], row["close_at"]
            data["totalPoints"], data["weight"] = row["set_total"], row["weight_pct"]
            data.update(changes)
            self._check_quiz(sql, row["offering_id"], data)
            repo.update_quiz(quiz_id, data)
            self._spread_points(sql, quiz_id)
            return self._teacher_view(sql, quiz_id)

    def add_question(self, *, actor: Actor, quiz_id: int, question: dict[str, Any]):
        with self.database.transaction() as connection:
            sql = Sql(connection)
            repo, row = self._draft_quiz(sql, actor, quiz_id)
            question_id = repo.insert_question(
                bank_id=repo.bank_id(row["offering_id"]), data=question
            )
            repo.add_to_quiz(quiz_id, question_id)
            self._spread_points(sql, quiz_id, {question_id: question})
            return self._teacher_view(sql, quiz_id)

    def replace_question(self, *, actor: Actor, quiz_id: int, question_id: int, question):
        """Edit a question; points left out = back to an equal share."""
        with self.database.transaction() as connection:
            sql = Sql(connection)
            repo, _ = self._draft_quiz(sql, actor, quiz_id)
            self._own_question(repo, quiz_id, question_id)
            repo.replace_question(question_id, question)
            self._spread_points(sql, quiz_id, {question_id: question})
            return self._teacher_view(sql, quiz_id)

    def remove_question(self, *, actor: Actor, quiz_id: int, question_id: int):
        with self.database.transaction() as connection:
            sql = Sql(connection)
            repo, _ = self._draft_quiz(sql, actor, quiz_id)
            self._own_question(repo, quiz_id, question_id)
            repo.remove_question(quiz_id, question_id)
            self._spread_points(sql, quiz_id)
            return self._teacher_view(sql, quiz_id)

    def publish_quiz(self, *, actor: Actor, quiz_id: int):
        """Freeze the questions and points; students can then take the quiz."""
        with self.database.transaction() as connection:
            sql = Sql(connection)
            repo, row = self._draft_quiz(sql, actor, quiz_id)
            questions = repo.questions(quiz_id)
            if not questions:
                raise conflict("QUIZ_EMPTY", "Add at least one question before publishing.")
            quiz_from_row(row).publish()
            repo.freeze(quiz_id, questions)
            repo.mark_published(quiz_id)
            AuditRepository(sql).record(
                actor_id=actor.user_id,
                action="QUIZ_PUBLISHED",
                target_type="QUIZ",
                target_id=quiz_id,
                details={"questions": len(questions)},
            )
            return self._teacher_view(sql, quiz_id)

    # ============================================================== student
    def start_attempt(self, *, actor: Actor, quiz_id: int):
        """Start (or resume the unfinished) attempt."""
        with self.database.transaction() as connection:
            sql = Sql(connection)
            row, _ = self._visible_quiz(sql, actor, quiz_id)
            require_student(CourseRepository(sql), actor, row["offering_id"])
            repo = QuizRepository(sql)
            repo.lock_student(row["offering_id"], actor.user_id)
            finish_expired(sql, offering_id=row["offering_id"], student_id=actor.user_id)
            attempts = repo.attempts(quiz_id, actor.user_id)
            running = [a for a in attempts if a["finalized_by"] is None]
            if running:
                return self._attempt_view(sql, running[0])
            now = AssessmentRepository(sql).db_now()
            quiz = quiz_from_row(row)
            if not quiz.is_open(now):
                if now < quiz.open_at:
                    raise conflict("QUIZ_NOT_OPEN", "This quiz has not opened yet.")
                raise conflict("QUIZ_CLOSED", "This quiz has closed.")
            if not quiz.can_start(len(attempts)):
                raise conflict("NO_ATTEMPTS_LEFT", "You have used all your attempts.")
            attempt_id = repo.insert_attempt(
                quiz_id=quiz_id,
                student_id=actor.user_id,
                attempt_no=len(attempts) + 1,
                started_at=now,
                ends_at=min(now + timedelta(minutes=quiz.duration_minutes), quiz.close_at),
            )
            return self._attempt_view(sql, repo.get_attempt(attempt_id))

    def get_attempt(self, *, actor: Actor, attempt_id: int):
        with self.database.transaction() as connection:
            sql = Sql(connection)
            row, _ = self._readable_attempt(sql, actor, attempt_id)
            return self._attempt_view(sql, row)

    def save_answer(self, *, actor: Actor, attempt_id: int, question_id: int, option: int):
        with self.database.transaction() as connection:
            sql = Sql(connection)
            repo = QuizRepository(sql)
            row = self._running_attempt(sql, actor, attempt_id)
            question = next(
                (
                    question_from_frozen(q)
                    for q in repo.frozen_questions(row["quiz_id"])
                    if q["quiz_question_id"] == question_id
                ),
                None,
            )
            if question is None:
                raise not_found("Question")
            if not 1 <= option <= len(question.options):
                raise ApiError(422, "INVALID_ANSWER", "Pick one of the question's options.")
            _load_attempt(repo, row).save_answer(question_id, option)
            repo.save_answer(
                attempt_id=attempt_id,
                quiz_id=row["quiz_id"],
                question_id=question_id,
                key=str(option),
                at=AssessmentRepository(sql).db_now(),
            )
            return {"questionId": question_id, "option": option}

    def seal(self, *, actor: Actor, attempt_id: int):
        """Submit the attempt; the score is calculated at once."""
        with self.database.transaction() as connection:
            sql = Sql(connection)
            row = self._running_attempt(sql, actor, attempt_id)
            _finish(sql, row, by="STUDENT", at=AssessmentRepository(sql).db_now())
            return self._attempt_view(sql, QuizRepository(sql).get_attempt(attempt_id))

    def get_quiz_result(self, *, actor: Actor, attempt_id: int):
        """Score of a finished attempt; right/wrong per question once the quiz closed
        (the professor always sees them)."""
        with self.database.transaction() as connection:
            sql = Sql(connection)
            row, teacher = self._readable_attempt(sql, actor, attempt_id)
            if row["finalized_by"] is None:
                raise conflict("ATTEMPT_IN_PROGRESS", "Submit the attempt first.")
            repo = QuizRepository(sql)
            quiz = quiz_from_row(repo.get_quiz(row["quiz_id"]))
            shown = teacher or AssessmentRepository(sql).db_now() >= quiz.close_at
            attempt = _load_attempt(repo, row)
            questions = []
            for q in repo.frozen_questions(row["quiz_id"]):
                question = question_from_frozen(q)
                chosen = attempt.answers.get(question.question_id)
                questions.append(
                    {
                        "id": question.question_id,
                        "position": q["position"],
                        "text": question.text,
                        "points": _num(question.points),
                        "selectedOption": chosen,
                        "correct": question.check_answer(chosen) if shown else None,
                        "correctOption": question.correct_option if shown else None,
                        "explanation": q["explanation"] if shown else None,
                    }
                )
            return {
                "attemptId": attempt_id,
                "quizId": row["quiz_id"],
                "attemptNo": row["attempt_no"],
                "score": _num(attempt.score),
                "maxScore": _num(quiz.max_score),
                "percentage": _num(Decimal(attempt.score) / quiz.max_score * 100),
                "answersShown": shown,
                "questions": questions,
            }

    def get_my_attempts(self, *, actor: Actor, quiz_id: int):
        """My attempts for a quiz, the score that counts and whether I can start another."""
        with self.database.transaction() as connection:
            sql = Sql(connection)
            row, _ = self._visible_quiz(sql, actor, quiz_id)
            finish_expired(sql, offering_id=row["offering_id"], student_id=actor.user_id)
            attempts = QuizRepository(sql).attempts(quiz_id, actor.user_id)
            quiz = quiz_from_row(row)
            finished = [Decimal(a["score"]) for a in attempts if a["finalized_by"]]
            now = AssessmentRepository(sql).db_now()
            running = any(a["finalized_by"] is None for a in attempts)
            return {
                "quizId": quiz_id,
                "maxAttempts": quiz.max_attempts,
                "attemptsUsed": len(attempts),
                "gradingMethod": quiz.grading_method.value,
                "countedScore": _num(quiz.counted_score(finished)),
                "maxScore": _num(quiz.max_score),
                "canStart": quiz.is_open(now) and (running or quiz.can_start(len(attempts))),
                "attempts": [attempt_summary(a) for a in attempts],
            }

    # ============================================================== helpers
    @staticmethod
    def _check_quiz(sql: Sql, offering_id: int, data: dict[str, Any]) -> None:
        if not data["title"].strip():
            raise ApiError(400, "INVALID_REQUEST", "Title must not be blank.")
        data["title"] = data["title"].strip()
        if not data["openAt"] + timedelta(minutes=data["durationMinutes"]) <= data["closeAt"]:
            raise ApiError(
                400, "INVALID_SCHEDULE", "The time limit must fit between opening and closing."
            )
        if data["topicId"] is not None:
            topic = ContentRepository(sql).get_topic(data["topicId"])
            if topic is None or topic.offering_id != offering_id:
                raise ApiError(422, "TOPIC_NOT_FOUND", "The topic is not in this class.")

    @staticmethod
    def _spread_points(sql: Sql, quiz_id: int, edited=None) -> None:
        """Recalculate every question's points with Quiz.distribute_points. edited =
        {question_id: request} for the question being saved (its points, or none for an
        equal share); other questions keep their hand-set points."""
        repo = QuizRepository(sql)
        quiz = quiz_from_row(repo.get_quiz(quiz_id))
        questions = repo.questions(quiz_id)
        edited = edited or {}
        custom = []
        for q in questions:
            if q["question_id"] in edited:
                value = edited[q["question_id"]].get("points")
                custom.append(None if value is None else Decimal(value))
            else:
                custom.append(Decimal(q["points"]) if q["is_custom_points"] else None)
        try:
            points = quiz.distribute_points(custom)
        except ValueError as error:
            raise ApiError(422, "INVALID_POINTS", str(error)) from None
        for q, value, hand_set in zip(questions, points, custom, strict=True):
            repo.set_points(quiz_id, q["question_id"], value, hand_set is not None)
        repo.set_quiz_total(quiz_id, quiz.max_score)
        repo.touch(quiz_id)

    def _teacher_view(self, sql: Sql, quiz_id: int) -> dict[str, Any]:
        repo = QuizRepository(sql)
        return {
            **quiz_view(repo.get_quiz(quiz_id)),
            "questions": [question_view(q) for q in repo.questions(quiz_id)],
        }

    @staticmethod
    def _visible_quiz(sql: Sql, actor: Actor, quiz_id: int):
        """Members see published quizzes; the professor also sees drafts."""
        row = QuizRepository(sql).get_quiz(quiz_id)
        if row is None:
            raise not_found("Quiz")
        member = require_member(CourseRepository(sql), actor, row["offering_id"])
        teacher = is_teacher(member)
        if not teacher and row["status"] == "DRAFT":
            raise not_found("Quiz")
        return row, teacher

    @staticmethod
    def _draft_quiz(sql: Sql, actor: Actor, quiz_id: int):
        repo = QuizRepository(sql)
        row = repo.get_quiz(quiz_id)
        if row is None:
            raise not_found("Quiz")
        require_teacher(CourseRepository(sql), actor, row["offering_id"])
        row = repo.get_quiz(quiz_id, lock=True)
        if row["status"] != "DRAFT":
            raise conflict("QUIZ_LOCKED", "A published quiz cannot be changed.")
        return repo, row

    @staticmethod
    def _own_question(repo: QuizRepository, quiz_id: int, question_id: int) -> None:
        if not any(q["question_id"] == question_id for q in repo.questions(quiz_id)):
            raise not_found("Question")

    @staticmethod
    def _readable_attempt(sql: Sql, actor: Actor, attempt_id: int):
        """The student who owns it, or the class professor."""
        repo = QuizRepository(sql)
        row = repo.get_attempt(attempt_id)
        if row is None:
            raise not_found("Attempt")
        quiz = repo.get_quiz(row["quiz_id"])
        member = require_member(CourseRepository(sql), actor, quiz["offering_id"])
        teacher = is_teacher(member)
        if row["student_id"] != actor.user_id and not teacher:
            raise not_found("Attempt")
        finish_expired(sql, offering_id=quiz["offering_id"], student_id=row["student_id"])
        return repo.get_attempt(attempt_id), teacher

    @staticmethod
    def _running_attempt(sql: Sql, actor: Actor, attempt_id: int):
        """The student's own unfinished attempt (finished here if its time ran out)."""
        repo = QuizRepository(sql)
        row = repo.get_attempt(attempt_id)
        if row is None or row["student_id"] != actor.user_id:
            raise not_found("Attempt")
        quiz = repo.get_quiz(row["quiz_id"])
        require_student(CourseRepository(sql), actor, quiz["offering_id"])
        row = repo.get_attempt(attempt_id, lock=True)
        attempt = _load_attempt(repo, row)
        if row["finalized_by"] is None and attempt.has_expired(AssessmentRepository(sql).db_now()):
            _finish(sql, row, by="SYSTEM", at=row["ends_at"])
            row = repo.get_attempt(attempt_id)
        if row["finalized_by"] is not None:
            raise conflict("ATTEMPT_FINISHED", "This attempt has already been submitted.")
        return row

    def _attempt_view(self, sql: Sql, row: dict[str, Any]) -> dict[str, Any]:
        """The student's quiz screen: questions without the right answers."""
        repo = QuizRepository(sql)
        attempt = _load_attempt(repo, row)
        return {
            **attempt_summary(row),
            "maxScore": _num(repo.get_quiz(row["quiz_id"])["max_score"]),
            "serverNow": AssessmentRepository(sql).db_now(),
            "questions": [
                {
                    "id": q["quiz_question_id"],
                    "position": q["position"],
                    "type": q["question_type"],
                    "text": q["prompt"],
                    "points": _num(q["points"]),
                    "options": [
                        {"number": n, "text": o["option_text"]}
                        for n, o in enumerate(q["options"], start=1)
                    ],
                    "selectedOption": attempt.answers.get(q["quiz_question_id"]),
                }
                for q in repo.frozen_questions(row["quiz_id"])
            ],
        }

    # ------------------------------------------- contract operations not used
    def finalize_expired_attempts(self, **kwargs: object):
        raise FeatureNotImplemented("QuizService.finalize_expired_attempts")

    def create_question_item(self, **kwargs: object):
        raise FeatureNotImplemented("QuizService.create_question_item")

    def edit_bank_question(self, **kwargs: object):
        raise FeatureNotImplemented("QuizService.edit_bank_question")

    def get_question_item(self, **kwargs: object):
        raise FeatureNotImplemented("QuizService.get_question_item")

    def list_question_items(self, **kwargs: object):
        raise FeatureNotImplemented("QuizService.list_question_items")
