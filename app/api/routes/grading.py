from fastapi import APIRouter, Path

from app.services.grading_service import GradingService

router = APIRouter(tags=["grading"], responses={400: {"description": "Invalid request"}})


@router.get("/me/grades", operation_id="getMyGrades", status_code=501)
def get_my_grades():
    return GradingService().get_my_grades()


@router.get(
    "/assignments/{assignmentId}/grade-records",
    operation_id="listAssignmentGradeRecords",
    status_code=501,
)
def list_assignment_grade_records(assignmentId: int = Path(ge=1, le=2147483647)):
    return GradingService().list_assignment_grade_records(assignment_id=assignmentId)


@router.get("/grade-records/{gradeRecordId}", operation_id="getGradeRecord", status_code=501)
def get_grade_record(gradeRecordId: int = Path(ge=1, le=2147483647)):
    return GradingService().get_grade_record(grade_record_id=gradeRecordId)


@router.post(
    "/grade-records/{gradeRecordId}/revisions", operation_id="createGradeRevision", status_code=501
)
def create_grade_revision(gradeRecordId: int = Path(ge=1, le=2147483647)):
    return GradingService().revise(grade_record_id=gradeRecordId)


@router.put(
    "/grade-records/{gradeRecordId}/publication",
    operation_id="publishGradeRevision",
    status_code=501,
)
def publish_grade_revision(gradeRecordId: int = Path(ge=1, le=2147483647)):
    return GradingService().publish(grade_record_id=gradeRecordId)


@router.get("/offerings/{offeringId}/gradebook", operation_id="getCourseGradebook", status_code=501)
def get_course_gradebook(offeringId: int = Path(ge=1, le=2147483647)):
    return GradingService().get_gradebook(offering_id=offeringId)


@router.get(
    "/offerings/{offeringId}/gradebook.csv", operation_id="exportGradebookCsv", status_code=501
)
def export_gradebook_csv(offeringId: int = Path(ge=1, le=2147483647)):
    return GradingService().export_gradebook_csv(offering_id=offeringId)


@router.post(
    "/submissions/{submissionId}/grade-record", operation_id="createInitialGrade", status_code=501
)
def create_initial_grade(submissionId: int = Path(ge=1, le=2147483647)):
    return GradingService().save_draft(submission_id=submissionId)


@router.post(
    "/assignments/{assignmentId}/missing-work-decisions",
    operation_id="confirmMissingWork",
    status_code=501,
)
def confirm_missing_work(assignmentId: int = Path(ge=1, le=2147483647)):
    return GradingService().confirm_missing_work(assignment_id=assignmentId)
