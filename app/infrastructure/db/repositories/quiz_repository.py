"MySQL SQL for quizzes, their questions, the frozen copy made at publish, and attempts. Never commits."

from datetime import datetime
from decimal import Decimal
from typing import Any

from app.infrastructure.db.sql import Sql

_QUIZ_SELECT = """SELECT a.activity_id, a.offering_id, a.topic_id, a.title, a.max_score,
        a.weight_pct, a.status, a.version, q.open_at, q.close_at, q.duration_min,
        q.max_attempts, q.grading_method, q.set_total, q.published_at, q.release_policy, a.is_mandatory,
        EXISTS (SELECT 1 FROM quiz_attempts t WHERE t.quiz_id=a.activity_id) AS schedule_locked,
        (SELECT COUNT(*) FROM quiz_questions AS qq WHERE qq.quiz_id = a.activity_id)
            AS question_count
    FROM activities AS a
    JOIN quizzes AS q ON q.activity_id = a.activity_id"""

_ATTEMPT_COLUMNS = """attempt_id, quiz_id, student_id, attempt_no, started_at, ends_at,
    submitted_at, finalized_by, score, released_at, processing_error, version"""


class QuizRepository:
    def __init__(self, sql: Sql):
        self.sql = sql

    # ------------------------------------------------------------------ quizzes
    def insert_quiz(self, *, offering_id: int, data: dict[str, Any]) -> int:
        quiz_id = self.sql.insert(
            """INSERT INTO activities (offering_id, topic_id, activity_type, title, max_score,
                   weight_pct, status)
               VALUES (%s, %s, 'QUIZ', %s, %s, %s, 'DRAFT')""",
            offering_id,
            data["topicId"],
            data["title"],
            data["totalPoints"],
            data["weight"],
        )
        self.sql.execute(
            """INSERT INTO quizzes (activity_id, open_at, close_at, duration_min, max_attempts,
                   grading_method, set_total)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            quiz_id,
            data["openAt"],
            data["closeAt"],
            data["durationMinutes"],
            data["maxAttempts"],
            data["gradingMethod"],
            data["totalPoints"],
        )
        self.sql.execute(
            "UPDATE quizzes SET release_policy=%s WHERE activity_id=%s",
            data["releasePolicy"],
            quiz_id,
        )
        self.sql.execute(
            "UPDATE activities SET is_mandatory=%s WHERE activity_id=%s", data["mandatory"], quiz_id
        )
        return quiz_id

    def get_quiz(self, quiz_id: int, *, lock: bool = False) -> dict[str, Any] | None:
        if lock:
            self.sql.execute("SELECT 1 FROM activities WHERE activity_id = %s FOR UPDATE", quiz_id)
        return self.sql.one(
            f"{_QUIZ_SELECT} WHERE a.activity_id = %s AND a.activity_type = 'QUIZ'", quiz_id
        )

    def list_quizzes(
        self, offering_id: int, *, published_only: bool, offset: int, limit: int
    ) -> tuple[list[dict[str, Any]], int]:
        where = "a.offering_id = %s AND a.activity_type = 'QUIZ'"
        if published_only:
            where += " AND a.status <> 'DRAFT'"
        total = self.sql.scalar(f"SELECT COUNT(*) FROM activities AS a WHERE {where}", offering_id)
        rows = self.sql.all(
            f"{_QUIZ_SELECT} WHERE {where} ORDER BY q.open_at, a.activity_id LIMIT %s, %s",
            offering_id,
            offset,
            limit,
        )
        return rows, total

    def update_quiz(self, quiz_id: int, data: dict[str, Any]) -> None:
        self.sql.execute(
            """UPDATE activities SET title = %s, topic_id = %s, max_score = %s, weight_pct = %s,
                   version = version + 1
               WHERE activity_id = %s""",
            data["title"],
            data["topicId"],
            data["totalPoints"],
            data["weight"],
            quiz_id,
        )
        self.sql.execute(
            """UPDATE quizzes SET open_at = %s, close_at = %s, duration_min = %s,
                   max_attempts = %s, grading_method = %s, set_total = %s
               WHERE activity_id = %s""",
            data["openAt"],
            data["closeAt"],
            data["durationMinutes"],
            data["maxAttempts"],
            data["gradingMethod"],
            data["totalPoints"],
            quiz_id,
        )

    def set_quiz_total(self, quiz_id: int, total: Decimal) -> None:
        """The total used for grading (the sum of points when all are set by hand)."""
        self.sql.execute(
            "UPDATE activities SET max_score = %s WHERE activity_id = %s",
            total,
            quiz_id,
        )

    def mark_published(self, quiz_id: int) -> None:
        self.sql.execute(
            """UPDATE activities SET status = 'PUBLISHED', version = version + 1
               WHERE activity_id = %s""",
            quiz_id,
        )
        self.sql.execute(
            "UPDATE quizzes SET published_at = UTC_TIMESTAMP(6) WHERE activity_id = %s", quiz_id
        )

    # ------------------------------------------------- questions (while draft)
    def bank_id(self, offering_id: int) -> int:
        """Questions are stored in one hidden bank per class."""
        bank = self.sql.scalar(
            "SELECT MIN(bank_id) FROM question_banks WHERE offering_id = %s", offering_id
        )
        if bank:
            return bank
        return self.sql.insert(
            "INSERT INTO question_banks (offering_id, title) VALUES (%s, 'Quiz questions')",
            offering_id,
        )

    def questions(self, quiz_id: int) -> list[dict[str, Any]]:
        rows = self.sql.all(
            """SELECT q.question_id, qq.position, qq.points, qq.is_custom_points,
                      q.question_type, q.question_text, q.tf_correct_answer, q.explanation, q.version, q.source_question_id, q.source_version
               FROM quiz_questions AS qq
               JOIN questions AS q ON q.question_id = qq.question_id
               WHERE qq.quiz_id = %s ORDER BY qq.position""",
            quiz_id,
        )
        options = self.sql.all(
            """SELECT o.question_id, o.option_no, o.option_text, o.is_correct
               FROM question_options AS o
               JOIN quiz_questions AS qq ON qq.question_id = o.question_id
               WHERE qq.quiz_id = %s ORDER BY o.question_id, o.option_no""",
            quiz_id,
        )
        for row in rows:
            row["options"] = [o for o in options if o["question_id"] == row["question_id"]]
        return rows

    def insert_question(self, *, bank_id: int, data: dict[str, Any]) -> int:
        question_id = self.sql.insert(
            """INSERT INTO questions (bank_id, question_type, question_text, points,
                   tf_correct_answer, explanation)
               VALUES (%s, %s, %s, 1, %s, %s)""",
            bank_id,
            data["type"],
            data["text"],
            data["correctAnswer"] if data["type"] == "TRUE_FALSE" else None,
            data["explanation"],
        )
        self._insert_options(question_id, data)
        return question_id

    def replace_question(self, question_id: int, data: dict[str, Any]) -> None:
        self.sql.execute("DELETE FROM question_options WHERE question_id = %s", question_id)
        self.sql.execute(
            """UPDATE questions SET question_type = %s, question_text = %s,
                   tf_correct_answer = %s, explanation = %s, version = version + 1
               WHERE question_id = %s""",
            data["type"],
            data["text"],
            data["correctAnswer"] if data["type"] == "TRUE_FALSE" else None,
            data["explanation"],
            question_id,
        )
        self._insert_options(question_id, data)

    def _insert_options(self, question_id: int, data: dict[str, Any]) -> None:
        if data["type"] != "SINGLE_CHOICE":
            return
        for number, text in enumerate(data["options"], start=1):
            self.sql.execute(
                """INSERT INTO question_options (question_id, option_no, option_text, is_correct)
                   VALUES (%s, %s, %s, %s)""",
                question_id,
                number,
                text,
                number == data["correctOption"],
            )

    def add_to_quiz(self, quiz_id: int, question_id: int) -> None:
        position = self.sql.scalar(
            "SELECT COALESCE(MAX(position), 0) + 1 FROM quiz_questions WHERE quiz_id = %s",
            quiz_id,
        )
        self.sql.execute(
            """INSERT INTO quiz_questions (quiz_id, question_id, position, points)
               VALUES (%s, %s, %s, 1)""",
            quiz_id,
            question_id,
            position,
        )

    def set_points(self, quiz_id: int, question_id: int, points: Decimal, custom: bool) -> None:
        self.sql.execute(
            """UPDATE quiz_questions SET points = %s, is_custom_points = %s
               WHERE quiz_id = %s AND question_id = %s""",
            points,
            custom,
            quiz_id,
            question_id,
        )
        self.sql.execute(
            "UPDATE questions SET points = %s WHERE question_id = %s", points, question_id
        )

    def remove_question(self, quiz_id: int, question_id: int) -> None:
        position = self.sql.scalar(
            "SELECT position FROM quiz_questions WHERE quiz_id = %s AND question_id = %s",
            quiz_id,
            question_id,
        )
        self.sql.execute(
            "DELETE FROM quiz_questions WHERE quiz_id = %s AND question_id = %s",
            quiz_id,
            question_id,
        )
        self.sql.execute(
            """UPDATE quiz_questions SET position = position - 1
               WHERE quiz_id = %s AND position > %s ORDER BY position""",
            quiz_id,
            position,
        )
        # Bank questions remain reusable after removing a quiz selection.

    def touch(self, quiz_id: int) -> None:
        self.sql.execute(
            "UPDATE activities SET version = version + 1 WHERE activity_id = %s", quiz_id
        )

    # ---------------------------------------------- frozen copy made at publish
    def freeze(self, quiz_id: int, questions: list[dict[str, Any]]) -> None:
        """Copy the questions at publish. Options are numbered 1, 2, ... (stored as text keys);
        true/false becomes 1 = True, 2 = False."""
        for question in questions:
            if question["question_type"] == "TRUE_FALSE":
                options = [("1", "True"), ("2", "False")]
                correct = "1" if question["tf_correct_answer"] else "2"
            else:
                options = [(str(o["option_no"]), o["option_text"]) for o in question["options"]]
                correct = next(str(o["option_no"]) for o in question["options"] if o["is_correct"])
            frozen_id = self.sql.insert(
                """INSERT INTO quiz_snapshot_questions (quiz_id, source_question_id, position,
                       question_type, prompt, correct_key, explanation, points, source_version)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                quiz_id,
                question.get("source_question_id") or question["question_id"],
                question["position"],
                question["question_type"],
                question["question_text"],
                correct,
                question["explanation"],
                question["points"],
                question.get("source_version") or question["version"],
            )
            for key, text in options:
                self.sql.execute(
                    """INSERT INTO quiz_snapshot_options (quiz_question_id, option_key, option_text)
                       VALUES (%s, %s, %s)""",
                    frozen_id,
                    key,
                    text,
                )

    def frozen_questions(self, quiz_id: int) -> list[dict[str, Any]]:
        rows = self.sql.all(
            """SELECT quiz_question_id, position, question_type, prompt, correct_key,
                      explanation, points
               FROM quiz_snapshot_questions WHERE quiz_id = %s ORDER BY position""",
            quiz_id,
        )
        options = self.sql.all(
            """SELECT o.quiz_question_id, o.option_key, o.option_text
               FROM quiz_snapshot_options AS o
               JOIN quiz_snapshot_questions AS q ON q.quiz_question_id = o.quiz_question_id
               WHERE q.quiz_id = %s
               ORDER BY o.quiz_question_id, CHAR_LENGTH(o.option_key), o.option_key""",
            quiz_id,
        )
        for row in rows:
            row["options"] = [
                o for o in options if o["quiz_question_id"] == row["quiz_question_id"]
            ]
        return rows

    # ----------------------------------------------------------------- attempts
    def lock_student(self, offering_id: int, student_id: int) -> None:
        """Serialise one student's attempt starts (two tabs cannot start two attempts)."""
        self.sql.execute(
            """SELECT 1 FROM course_memberships WHERE offering_id = %s AND user_id = %s
               FOR UPDATE""",
            offering_id,
            student_id,
        )

    def attempts(self, quiz_id: int, student_id: int) -> list[dict[str, Any]]:
        return self.sql.all(
            f"""SELECT {_ATTEMPT_COLUMNS} FROM quiz_attempts
                WHERE quiz_id = %s AND student_id = %s ORDER BY attempt_no""",
            quiz_id,
            student_id,
        )

    def get_attempt(self, attempt_id: int, *, lock: bool = False) -> dict[str, Any] | None:
        return self.sql.one(
            f"SELECT {_ATTEMPT_COLUMNS} FROM quiz_attempts WHERE attempt_id = %s"
            + (" FOR UPDATE" if lock else ""),
            attempt_id,
        )

    def insert_attempt(
        self,
        *,
        quiz_id: int,
        student_id: int,
        attempt_no: int,
        started_at: datetime,
        ends_at: datetime,
    ) -> int:
        return self.sql.insert(
            """INSERT INTO quiz_attempts (quiz_id, student_id, attempt_no, started_at, ends_at)
               VALUES (%s, %s, %s, %s, %s)""",
            quiz_id,
            student_id,
            attempt_no,
            started_at,
            ends_at,
        )

    def answers(self, attempt_id: int) -> dict[int, dict[str, Any]]:
        rows = self.sql.all(
            """SELECT quiz_question_id, selected_key, is_correct
               FROM attempt_answers WHERE attempt_id = %s""",
            attempt_id,
        )
        return {r["quiz_question_id"]: r for r in rows}

    def save_answer(
        self, *, attempt_id: int, quiz_id: int, question_id: int, key: str, at: datetime
    ) -> None:
        self.sql.execute(
            """INSERT INTO attempt_answers (attempt_id, quiz_id, quiz_question_id, selected_key,
                   saved_at)
               VALUES (%s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE selected_key = VALUES(selected_key),
                   saved_at = VALUES(saved_at)""",
            attempt_id,
            quiz_id,
            question_id,
            key,
            at,
        )

    def finish(self, *, attempt_id: int, by: str, at: datetime, score: Decimal) -> None:
        """Mark answers right/wrong and store the score (shown to the student at once)."""
        self.sql.execute(
            """UPDATE attempt_answers AS a
               JOIN quiz_snapshot_questions AS q ON q.quiz_question_id = a.quiz_question_id
               SET a.is_correct = (a.selected_key = q.correct_key)
               WHERE a.attempt_id = %s""",
            attempt_id,
        )
        self.sql.execute(
            """UPDATE quiz_attempts SET submitted_at = %s, finalized_by = %s, score = %s,
                   processing_error=NULL, version = version + 1
               WHERE attempt_id = %s""",
            at,
            by,
            score,
            attempt_id,
        )

    def expired_unfinished(
        self, now: datetime, *, offering_id: int | None = None, student_id: int | None = None
    ) -> list[int]:
        where, params = ["t.finalized_by IS NULL", "t.ends_at <= %s"], [now]
        if offering_id is not None:
            where.append("a.offering_id = %s")
            params.append(offering_id)
        if student_id is not None:
            where.append("t.student_id = %s")
            params.append(student_id)
        return [
            r["attempt_id"]
            for r in self.sql.all(
                f"""SELECT t.attempt_id FROM quiz_attempts AS t
                    JOIN activities AS a ON a.activity_id = t.quiz_id
                    WHERE {" AND ".join(where)} FOR UPDATE""",
                *params,
            )
        ]

    # --------------------------------------------------------------- grade page
    def quiz_grade_rows(self, offering_id: int, student_id: int) -> list[dict[str, Any]]:
        """Published quizzes of the class with the student's finished attempt scores."""
        quizzes = self.sql.all(
            f"""{_QUIZ_SELECT} WHERE a.offering_id = %s AND a.activity_type = 'QUIZ'
                  AND a.status <> 'DRAFT' ORDER BY q.close_at, a.activity_id""",
            offering_id,
        )
        scores = self.sql.all(
            """SELECT t.quiz_id, t.score FROM quiz_attempts AS t
               JOIN activities AS a ON a.activity_id = t.quiz_id
               WHERE a.offering_id = %s AND t.student_id = %s AND t.finalized_by IS NOT NULL AND t.released_at IS NOT NULL
               ORDER BY t.attempt_no""",
            offering_id,
            student_id,
        )
        for quiz in quizzes:
            quiz["scores"] = [s["score"] for s in scores if s["quiz_id"] == quiz["activity_id"]]
        return quizzes
