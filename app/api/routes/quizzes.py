from typing import Annotated

from fastapi import APIRouter, Path, Query, Response

from app.api.dependencies import (
    ActorDep,
    DatabaseDep,
    MutationActorDep,
    QuizServiceDep,
    VersionDep,
    set_etag,
)
from app.api.schemas.quiz import (
    AnswerRequest,
    AttemptView,
    BankQuestion,
    BankQuestionPage,
    MyQuizAttempts,
    QuestionRequest,
    QuizPage,
    QuizRequest,
    QuizResult,
    QuizView,
    UpdateQuizRequest,
)
from app.services.question_bank_service import QuestionBankService
from app.services.quiz_service import QuizService

router = APIRouter(tags=["quizzes"], responses={400: {"description": "Invalid request"}})

OfferingId = Annotated[int, Path(alias="offeringId", ge=1, le=2147483647)]
QuizId = Annotated[int, Path(alias="quizId", ge=1, le=2147483647)]
AttemptId = Annotated[int, Path(alias="attemptId", ge=1, le=2147483647)]
QuestionId = Annotated[int, Path(alias="questionId", ge=1, le=2147483647)]


# ================================================================ professor
@router.get(
    "/offerings/{offeringId}/quizzes",
    operation_id="listQuizzes",
    response_model=QuizPage,
    summary="Quizzes of a class; students see published ones only.",
)
def list_quizzes(
    offering_id: OfferingId,
    actor: ActorDep,
    service: QuizServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    pageSize: Annotated[int, Query(ge=1, le=100)] = 50,
):
    return service.list_quizzes(actor=actor, offering_id=offering_id, page=page, page_size=pageSize)


@router.post(
    "/offerings/{offeringId}/quizzes",
    operation_id="createQuiz",
    status_code=201,
    response_model=QuizView,
    summary="Professor creates a draft quiz (total points, time limit, attempts, counted attempt).",
)
def create_quiz(
    offering_id: OfferingId,
    body: QuizRequest,
    actor: MutationActorDep,
    response: Response,
    service: QuizServiceDep,
):
    view = service.create_quiz(actor=actor, offering_id=offering_id, data=body.model_dump())
    response.headers["Location"] = f"/api/v1/quizzes/{view['id']}"
    set_etag(response, view["version"])
    return view


@router.get(
    "/quizzes/{quizId}",
    operation_id="getQuiz",
    response_model=QuizView,
    summary="Quiz settings; the professor also gets the questions with answers.",
)
def get_quiz(quiz_id: QuizId, actor: ActorDep, response: Response, service: QuizServiceDep):
    view = service.get_quiz(actor=actor, quiz_id=quiz_id)
    set_etag(response, view["version"])
    return view


@router.patch(
    "/quizzes/{quizId}",
    operation_id="updateQuiz",
    response_model=QuizView,
    summary="Change a draft quiz's settings. Needs If-Match.",
    responses={409: {"description": "QUIZ_LOCKED"}, 412: {"description": "VERSION_CONFLICT"}},
)
def update_quiz(
    quiz_id: QuizId,
    body: UpdateQuizRequest,
    actor: MutationActorDep,
    version: VersionDep,
    response: Response,
    service: QuizServiceDep,
):
    view = service.update_quiz(
        actor=actor,
        quiz_id=quiz_id,
        expected_version=version,
        changes=body.model_dump(exclude_unset=True),
    )
    set_etag(response, view["version"])
    return view


@router.post(
    "/quizzes/{quizId}/questions",
    operation_id="addQuizQuestion",
    status_code=201,
    response_model=QuizView,
    summary="Add a question to a draft quiz; points are re-shared.",
    responses={422: {"description": "INVALID_POINTS"}},
)
def add_quiz_question(
    quiz_id: QuizId, body: QuestionRequest, actor: MutationActorDep, service: QuizServiceDep
):
    return service.add_question(actor=actor, quiz_id=quiz_id, question=body.model_dump())


@router.put(
    "/quizzes/{quizId}/questions/{questionId}",
    operation_id="replaceQuizQuestion",
    response_model=QuizView,
    summary="Replace a question of a draft quiz (no points = equal share).",
    responses={422: {"description": "INVALID_POINTS"}},
)
def replace_quiz_question(
    quiz_id: QuizId,
    question_id: QuestionId,
    body: QuestionRequest,
    actor: MutationActorDep,
    service: QuizServiceDep,
):
    return service.replace_question(
        actor=actor, quiz_id=quiz_id, question_id=question_id, question=body.model_dump()
    )


@router.delete(
    "/quizzes/{quizId}/questions/{questionId}",
    operation_id="removeQuizQuestion",
    response_model=QuizView,
    summary="Remove a question from a draft quiz; points are re-shared.",
)
def remove_quiz_question(
    quiz_id: QuizId, question_id: QuestionId, actor: MutationActorDep, service: QuizServiceDep
):
    return service.remove_question(actor=actor, quiz_id=quiz_id, question_id=question_id)


@router.put(
    "/quizzes/{quizId}/publication",
    operation_id="publishQuiz",
    response_model=QuizView,
    summary="Publish: questions and points are frozen and students can take the quiz.",
    responses={409: {"description": "QUIZ_EMPTY or QUIZ_LOCKED"}},
)
def publish_quiz(quiz_id: QuizId, actor: MutationActorDep, service: QuizServiceDep):
    return service.publish_quiz(actor=actor, quiz_id=quiz_id)


# ================================================================== student
@router.post(
    "/quizzes/{quizId}/attempts",
    operation_id="startQuizAttempt",
    status_code=201,
    response_model=AttemptView,
    summary="Student starts an attempt (or gets back the one still running).",
    responses={409: {"description": "QUIZ_NOT_OPEN, QUIZ_CLOSED or NO_ATTEMPTS_LEFT"}},
)
def start_quiz_attempt(quiz_id: QuizId, actor: MutationActorDep, service: QuizServiceDep):
    return service.start_attempt(actor=actor, quiz_id=quiz_id)


@router.get(
    "/quizzes/{quizId}/attempts/me",
    operation_id="getOwnQuizAttempt",
    response_model=MyQuizAttempts,
    summary="Student: my attempts, the score that counts and whether I can start another.",
)
def get_own_quiz_attempt(quiz_id: QuizId, actor: ActorDep, service: QuizServiceDep):
    return service.get_my_attempts(actor=actor, quiz_id=quiz_id)


@router.get(
    "/quiz-attempts/{attemptId}",
    operation_id="getQuizAttempt",
    response_model=AttemptView,
    summary="The attempt screen: questions (no right answers), saved answers, end time.",
)
def get_quiz_attempt(attempt_id: AttemptId, actor: ActorDep, service: QuizServiceDep):
    return service.get_attempt(actor=actor, attempt_id=attempt_id)


@router.put(
    "/quiz-attempts/{attemptId}/answers/{questionId}",
    operation_id="saveQuizAnswer",
    response_model=AttemptView,
    summary="Save (or change) one answer while the attempt is running.",
    responses={409: {"description": "ATTEMPT_FINISHED"}, 422: {"description": "INVALID_ANSWER"}},
)
def save_quiz_answer(
    attempt_id: AttemptId,
    question_id: QuestionId,
    body: AnswerRequest,
    version: VersionDep,
    actor: MutationActorDep,
    service: QuizServiceDep,
):
    return service.save_answer(
        actor=actor,
        attempt_id=attempt_id,
        question_id=question_id,
        option=body.option,
        expected_version=version,
    )


@router.post(
    "/quiz-attempts/{attemptId}/seal",
    operation_id="sealQuizAttempt",
    response_model=AttemptView,
    summary="Submit the attempt; it is scored at once.",
    responses={409: {"description": "ATTEMPT_FINISHED"}},
)
def seal_quiz_attempt(
    attempt_id: AttemptId, version: VersionDep, actor: MutationActorDep, service: QuizServiceDep
):
    return service.seal(actor=actor, attempt_id=attempt_id, expected_version=version)


@router.get(
    "/quiz-attempts/{attemptId}/result",
    operation_id="getQuizResult",
    response_model=QuizResult,
    summary="Score of a finished attempt; right/wrong answers after the quiz closes.",
)
def get_quiz_result(attempt_id: AttemptId, actor: ActorDep, service: QuizServiceDep):
    return service.get_quiz_result(actor=actor, attempt_id=attempt_id)


# The bank reuses the main numeric question format.


@router.get(
    "/offerings/{offeringId}/question-bank-items",
    operation_id="listQuestionItems",
    response_model=BankQuestionPage,
)
def list_question_items(
    offering_id: OfferingId,
    actor: ActorDep,
    database: DatabaseDep,
    q: str | None = None,
    kind: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    pageSize: Annotated[int, Query(ge=1, le=100)] = 25,
):
    return QuestionBankService(database).list(
        actor=actor, offering_id=offering_id, search=q, kind=kind, page=page, page_size=pageSize
    )


@router.post(
    "/offerings/{offeringId}/question-bank-items",
    operation_id="createQuestionItem",
    response_model=BankQuestion,
    status_code=201,
)
def create_question_item(
    offering_id: OfferingId, body: QuestionRequest, actor: MutationActorDep, database: DatabaseDep
):
    return QuestionBankService(database).save(
        actor=actor, offering_id=offering_id, data=body.model_dump()
    )


QuestionItemId = Annotated[int, Path(alias="questionItemId", ge=1, le=2147483647)]


@router.get(
    "/question-bank-items/{questionItemId}",
    operation_id="getQuestionItem",
    response_model=BankQuestion,
)
def get_question_item(question_id: QuestionItemId, actor: ActorDep, database: DatabaseDep):
    return QuestionBankService(database).get(actor=actor, question_id=question_id)


@router.patch(
    "/question-bank-items/{questionItemId}",
    operation_id="updateQuestionItem",
    response_model=BankQuestion,
)
def update_question_item(
    question_id: QuestionItemId,
    body: QuestionRequest,
    actor: MutationActorDep,
    version: VersionDep,
    database: DatabaseDep,
):
    return QuestionBankService(database).save(
        actor=actor, question_id=question_id, data=body.model_dump(), expected_version=version
    )


@router.get("/quizzes/{quizId}/attempts", operation_id="listQuizAttempts")
def list_attempts(
    quiz_id: QuizId,
    actor: ActorDep,
    database: DatabaseDep,
    page: Annotated[int, Query(ge=1)] = 1,
    pageSize: Annotated[int, Query(ge=1, le=100)] = 25,
):
    from app.core.errors import forbidden
    from app.infrastructure.db.repositories.course_repository import CourseRepository
    from app.infrastructure.db.repositories.quiz_repository import QuizRepository
    from app.infrastructure.db.sql import Sql
    from app.services.access import is_teacher, require_member

    with database.read_connection() as connection:
        sql = Sql(connection)
        quiz = QuizRepository(sql).get_quiz(quiz_id)
        if quiz is None:
            from app.core.errors import not_found

            raise not_found("Quiz")
        if not is_teacher(require_member(CourseRepository(sql), actor, quiz["offering_id"])):
            raise forbidden()
        rows = sql.all(
            "SELECT attempt_id FROM quiz_attempts WHERE quiz_id=%s ORDER BY student_id,attempt_no",
            quiz_id,
        )
    ids = rows[(page - 1) * pageSize : page * pageSize]
    service = QuizService(database)
    return {
        "items": [service.get_attempt(actor=actor, attempt_id=r["attempt_id"]) for r in ids],
        "page": page,
        "pageSize": pageSize,
        "totalItems": len(rows),
        "totalPages": (len(rows) + pageSize - 1) // pageSize,
    }
