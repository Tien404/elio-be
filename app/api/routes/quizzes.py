from fastapi import APIRouter, Path

from app.services.quiz_service import QuizService

router = APIRouter(tags=["quizzes"], responses={400: {"description": "Invalid request"}})


@router.get(
    "/offerings/{offeringId}/question-bank-items", operation_id="listQuestionItems", status_code=501
)
def list_question_items(offeringId: int = Path(ge=1, le=2147483647)):
    return QuizService().list_question_items(offering_id=offeringId)


@router.post(
    "/offerings/{offeringId}/question-bank-items",
    operation_id="createQuestionItem",
    status_code=501,
)
def create_question_item(offeringId: int = Path(ge=1, le=2147483647)):
    return QuizService().create_question_item(offering_id=offeringId)


@router.get(
    "/question-bank-items/{questionItemId}", operation_id="getQuestionItem", status_code=501
)
def get_question_item(questionItemId: int = Path(ge=1, le=2147483647)):
    return QuizService().get_question_item(question_item_id=questionItemId)


@router.patch(
    "/question-bank-items/{questionItemId}", operation_id="updateQuestionItem", status_code=501
)
def update_question_item(questionItemId: int = Path(ge=1, le=2147483647)):
    return QuizService().edit_bank_question(question_item_id=questionItemId)


@router.get("/offerings/{offeringId}/quizzes", operation_id="listQuizzes", status_code=501)
def list_quizzes(offeringId: int = Path(ge=1, le=2147483647)):
    return QuizService().list_quizzes(offering_id=offeringId)


@router.post("/offerings/{offeringId}/quizzes", operation_id="createQuiz", status_code=501)
def create_quiz(offeringId: int = Path(ge=1, le=2147483647)):
    return QuizService().create_quiz(offering_id=offeringId)


@router.get("/quizzes/{quizId}", operation_id="getQuiz", status_code=501)
def get_quiz(quizId: int = Path(ge=1, le=2147483647)):
    return QuizService().get_quiz(quiz_id=quizId)


@router.patch("/quizzes/{quizId}", operation_id="updateQuiz", status_code=501)
def update_quiz(quizId: int = Path(ge=1, le=2147483647)):
    return QuizService().update_quiz(quiz_id=quizId)


@router.put("/quizzes/{quizId}/publication", operation_id="publishQuiz", status_code=501)
def publish_quiz(quizId: int = Path(ge=1, le=2147483647)):
    return QuizService().publish_quiz(quiz_id=quizId)


@router.post("/quizzes/{quizId}/attempts", operation_id="startQuizAttempt", status_code=501)
def start_quiz_attempt(quizId: int = Path(ge=1, le=2147483647)):
    return QuizService().start_attempt(quiz_id=quizId)


@router.get("/quiz-attempts/{attemptId}", operation_id="getQuizAttempt", status_code=501)
def get_quiz_attempt(attemptId: int = Path(ge=1, le=2147483647)):
    return QuizService().get_quiz_attempt(attempt_id=attemptId)


@router.put(
    "/quiz-attempts/{attemptId}/answers/{questionId}",
    operation_id="saveQuizAnswer",
    status_code=501,
)
def save_quiz_answer(
    attemptId: int = Path(ge=1, le=2147483647), questionId: int = Path(ge=1, le=2147483647)
):
    return QuizService().save_answer(attempt_id=attemptId, question_id=questionId)


@router.post("/quiz-attempts/{attemptId}/seal", operation_id="sealQuizAttempt", status_code=501)
def seal_quiz_attempt(attemptId: int = Path(ge=1, le=2147483647)):
    return QuizService().seal(attempt_id=attemptId)


@router.get("/quiz-attempts/{attemptId}/result", operation_id="getQuizResult", status_code=501)
def get_quiz_result(attemptId: int = Path(ge=1, le=2147483647)):
    return QuizService().get_quiz_result(attempt_id=attemptId)


@router.get("/quizzes/{quizId}/attempts/me", operation_id="getOwnQuizAttempt", status_code=501)
def get_own_quiz_attempt(quizId: int = Path(ge=1, le=2147483647)):
    return QuizService().get_own_quiz_attempt(quiz_id=quizId)
