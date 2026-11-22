"""Quiz screens: professor's quiz editor, student's attempt screen and result."""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from app.api.schemas.common import Id, Instant, PageMeta, RequestModel, ResponseModel, Version
from app.api.schemas.identity import AccountSummary

Title = Annotated[str, Field(min_length=1, max_length=200)]
Points = Annotated[Decimal, Field(gt=0, max_digits=5, decimal_places=2)]
QuestionKind = Literal["SINGLE_CHOICE", "TRUE_FALSE"]
Method = Literal["HIGHEST_SCORE", "LATEST_ATTEMPT", "AVERAGE"]


class BankSelection(RequestModel):
    questionItemId: Id
    points: Points | None = None


class QuizRequest(RequestModel):
    title: Title
    topicId: Id | None = None
    openAt: AwareDatetime
    closeAt: AwareDatetime
    durationMinutes: Annotated[int, Field(ge=1, le=1440)]
    totalPoints: Annotated[Decimal, Field(gt=0, max_digits=6, decimal_places=2)]
    weight: Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)] = Decimal(0)
    maxAttempts: Annotated[int, Field(ge=0, le=100, description="0 = unlimited")] = 1
    releasePolicy: Literal["AFTER_CLOSE", "IMMEDIATE"] = "AFTER_CLOSE"
    mandatory: bool = False
    questions: list[BankSelection] = []
    gradingMethod: Method = "HIGHEST_SCORE"


class UpdateQuizRequest(RequestModel):
    title: Title | None = None
    topicId: Id | None = None
    openAt: AwareDatetime | None = None
    closeAt: AwareDatetime | None = None
    durationMinutes: Annotated[int, Field(ge=1, le=1440)] | None = None
    totalPoints: Annotated[Decimal, Field(gt=0, max_digits=6, decimal_places=2)] | None = None
    weight: Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)] | None = None
    maxAttempts: Annotated[int, Field(ge=0, le=100)] | None = None
    releasePolicy: Literal["AFTER_CLOSE", "IMMEDIATE"] | None = None
    mandatory: bool | None = None
    questions: list[BankSelection] | None = None
    status: Literal["ARCHIVED"] | None = None
    gradingMethod: Method | None = None


class QuestionRequest(RequestModel):
    """Single choice: options + correctOption (1 = first option).
    True/false: correctAnswer. points left out = equal share of the quiz total."""

    type: QuestionKind
    text: Annotated[str, Field(min_length=1, max_length=5000)]
    options: (
        Annotated[
            list[Annotated[str, Field(min_length=1, max_length=1000)]],
            Field(min_length=2, max_length=8),
        ]
        | None
    ) = None
    correctOption: Annotated[int, Field(ge=1, le=8)] | None = None
    correctAnswer: bool | None = None
    explanation: Annotated[str, Field(max_length=5000)] | None = None
    points: Points | None = None

    @model_validator(mode="after")
    def answer_matches_type(self):
        if self.type == "SINGLE_CHOICE":
            if self.options is None or self.correctOption is None or self.correctAnswer is not None:
                raise ValueError("Single choice needs options and correctOption")
            if self.correctOption > len(self.options):
                raise ValueError("correctOption must point at one of the options")
        elif self.correctAnswer is None or self.options is not None or self.correctOption:
            raise ValueError("True/false needs correctAnswer only")
        return self


class AnswerRequest(RequestModel):
    option: Annotated[
        int, Field(ge=1, le=8, description="Option number; true/false: 1 = True, 2 = False")
    ]


class QuizQuestion(ResponseModel):
    sourceQuestionId: Id | None
    sourceVersion: Version | None
    id: Id
    position: int
    type: QuestionKind
    text: str
    options: list[str] | None
    correctOption: int | None
    correctAnswer: bool | None
    explanation: str | None
    points: float
    customPoints: bool


class QuizView(ResponseModel):
    id: Id
    offeringId: Id
    topicId: Id | None
    title: str
    status: Literal["DRAFT", "PUBLISHED", "ARCHIVED"]
    openAt: Instant
    closeAt: Instant
    durationMinutes: int
    totalPoints: float
    weight: float
    maxAttempts: int
    releasePolicy: Literal["AFTER_CLOSE", "IMMEDIATE"]
    mandatory: bool
    serverNow: Instant
    scheduleLocked: bool
    gradingMethod: Method
    questionCount: int
    version: Version
    questions: list[QuizQuestion] | None = Field(
        default=None, description="Professor only; null for students."
    )


class QuizPage(PageMeta):
    items: list[QuizView]


class AttemptOption(ResponseModel):
    number: int
    text: str


class AttemptQuestion(ResponseModel):
    id: Id
    position: int
    type: QuestionKind
    text: str
    points: float
    options: list[AttemptOption]
    selectedOption: int | None


class AttemptSummary(ResponseModel):
    version: Version
    releasedAt: Instant | None
    id: Id
    quizId: Id
    attemptNo: int
    startedAt: Instant
    endsAt: Instant
    submittedAt: Instant | None
    finishedBy: Literal["STUDENT", "SYSTEM"] | None
    status: Literal["IN_PROGRESS", "FINISHED"]
    score: float | None


class AttemptView(AttemptSummary):
    student: AccountSummary
    finalization: Literal["PENDING", "SUCCEEDED", "ERROR"]
    savedAt: dict[str, Instant]
    maxScore: float
    serverNow: Instant
    questions: list[AttemptQuestion]


class SavedAnswer(ResponseModel):
    questionId: Id
    option: int


class ResultQuestion(ResponseModel):
    id: Id
    position: int
    text: str
    points: float
    selectedOption: int | None
    correct: bool | None
    correctOption: int | None
    explanation: str | None


class QuizResult(ResponseModel):
    attemptId: Id
    quizId: Id
    attemptNo: int
    state: Literal[
        "PUBLISHED", "PROCESSING", "WAITING_FOR_CLOSE", "WAITING_FOR_RESTORE", "GRADING_ERROR"
    ]
    releasedAt: Instant | None
    score: float | None = None
    maxScore: float
    percentage: float | None = None
    answersShown: bool = Field(description="Right/wrong is shown after the quiz closes.")
    questions: list[ResultQuestion]


class MyQuizAttempts(ResponseModel):
    quizId: Id
    maxAttempts: int
    attemptsUsed: int
    gradingMethod: Method
    countedScore: float | None
    maxScore: float
    canStart: bool
    attempts: list[AttemptSummary]


class BankQuestion(QuestionRequest):
    points: float
    id: Id
    offeringId: Id
    version: Version


class BankQuestionPage(PageMeta):
    items: list[BankQuestion]
