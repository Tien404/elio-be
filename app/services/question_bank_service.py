"""Editable bank questions, using the main quiz repository and numeric options."""

from app.core.errors import conflict, not_found, version_conflict
from app.infrastructure.db.repositories.course_repository import CourseRepository
from app.infrastructure.db.repositories.quiz_repository import QuizRepository
from app.infrastructure.db.sql import Sql, like_literal
from app.services.access import require_teacher


def bank_question(sql, question_id):
    row = sql.one(
        """SELECT q.*,b.offering_id FROM questions q JOIN question_banks b
        ON b.bank_id=q.bank_id WHERE q.question_id=%s""",
        question_id,
    )
    if row is None:
        raise not_found("Question")
    options = sql.all(
        "SELECT * FROM question_options WHERE question_id=%s ORDER BY option_no", question_id
    )
    return {
        "id": question_id,
        "offeringId": row["offering_id"],
        "version": row["version"],
        "type": row["question_type"],
        "text": row["question_text"],
        "points": float(row["points"]),
        "explanation": row["explanation"],
        "options": [o["option_text"] for o in options] if options else None,
        "correctOption": next((o["option_no"] for o in options if o["is_correct"]), None),
        "correctAnswer": bool(row["tf_correct_answer"])
        if row["question_type"] == "TRUE_FALSE"
        else None,
    }


class QuestionBankService:
    def __init__(self, database):
        self.database = database

    def list(self, *, actor, offering_id, search=None, kind=None, page=1, page_size=25):
        with self.database.transaction() as connection:
            sql = Sql(connection)
            require_teacher(CourseRepository(sql), actor, offering_id)
            where = "b.offering_id=%s AND q.source_question_id IS NULL AND q.question_text LIKE %s ESCAPE '!'"
            params = [offering_id, "%" + like_literal(search or "") + "%"]
            if kind:
                where += " AND q.question_type=%s"
                params.append(kind)
            source = "FROM questions q JOIN question_banks b ON b.bank_id=q.bank_id"
            total = sql.scalar(f"SELECT COUNT(*) {source} WHERE {where}", *params)
            rows = sql.all(
                f"SELECT q.question_id {source} WHERE {where} ORDER BY q.question_id DESC LIMIT %s,%s",
                *params,
                (page - 1) * page_size,
                page_size,
            )
            return {
                "items": [bank_question(sql, r["question_id"]) for r in rows],
                "page": page,
                "pageSize": page_size,
                "totalItems": total,
                "totalPages": (total + page_size - 1) // page_size,
            }

    def get(self, *, actor, question_id):
        with self.database.transaction() as connection:
            sql = Sql(connection)
            view = bank_question(sql, question_id)
            require_teacher(CourseRepository(sql), actor, view["offeringId"])
            return view

    def save(self, *, actor, offering_id=None, question_id=None, data, expected_version=None):
        with self.database.transaction() as connection:
            sql = Sql(connection)
            repo = QuizRepository(sql)
            if question_id is not None:
                old = bank_question(sql, question_id)
                offering_id = old["offeringId"]
            require_teacher(CourseRepository(sql), actor, offering_id)
            if question_id is not None:
                sql.execute(
                    "SELECT question_id FROM questions WHERE question_id=%s FOR UPDATE", question_id
                )
                old = bank_question(sql, question_id)
                if sql.scalar(
                    "SELECT COUNT(*) FROM questions q WHERE q.question_id=%s AND (q.source_question_id IS NOT NULL OR EXISTS (SELECT 1 FROM quiz_questions qq JOIN activities a ON a.activity_id=qq.quiz_id WHERE qq.question_id=q.question_id AND a.status<>'DRAFT'))",
                    question_id,
                ):
                    raise conflict(
                        "QUESTION_COPY_LOCKED",
                        "Edit the source bank question; published quiz copies are fixed.",
                    )
                if old["version"] != expected_version:
                    raise version_conflict(old["version"])
                repo.replace_question(question_id, data)
            else:
                bank = sql.scalar(
                    "SELECT bank_id FROM question_banks WHERE offering_id=%s AND title='Question bank' ORDER BY bank_id LIMIT 1",
                    offering_id,
                )
                if bank is None:
                    bank = sql.insert(
                        "INSERT INTO question_banks (offering_id,title) VALUES (%s,'Question bank')",
                        offering_id,
                    )
                question_id = repo.insert_question(bank_id=bank, data=data)
            sql.execute(
                "UPDATE questions SET points=%s WHERE question_id=%s",
                data.get("points") or 1,
                question_id,
            )
            return bank_question(sql, question_id)
