from .administration import router as administration
from .assignments import router as assignments
from .content import router as content
from .enrollment import router as enrollment
from .files import router as files
from .grading import router as grading
from .groups import router as groups
from .identity import router as identity
from .notifications import router as notifications
from .offerings import router as offerings
from .progress import router as progress
from .projections import router as projections
from .quizzes import router as quizzes
from .submissions import router as submissions
from .teaching import router as teaching

ROUTERS = [
    administration,
    assignments,
    content,
    enrollment,
    files,
    grading,
    groups,
    identity,
    notifications,
    offerings,
    progress,
    projections,
    quizzes,
    submissions,
    teaching,
]
