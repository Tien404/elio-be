from typing import Annotated

from fastapi import APIRouter, Path, Response

from app.api.dependencies import ActorDep, GradingServiceDep, MutationActorDep, VersionDep
from app.api.schemas.grading import (
    AssignmentGradeRecords,
    Gradebook,
    GradebookWeights,
    GradeRecord,
    GradeRelease,
    GradeReport,
    GradeRequest,
    MissingWorkRequest,
    MyGrades,
    PublishGradeRequest,
)
from app.domain.entities import SpecialMark

router = APIRouter(tags=["grading"], responses={400: {"description": "Invalid request"}})

OfferingId = Annotated[int, Path(alias="offeringId", ge=1, le=2147483647)]
AssignmentId = Annotated[int, Path(alias="assignmentId", ge=1, le=2147483647)]


def _mark(name: str | None) -> SpecialMark | None:
    return SpecialMark(name) if name else None


@router.get(
    "/me/grades",
    operation_id="getMyGrades",
    response_model=MyGrades,
    summary="Student: my grade report per class (released grades only).",
)
def get_my_grades(actor: ActorDep, service: GradingServiceDep):
    return service.get_my_grades(actor=actor)


@router.get(
    "/offerings/{offeringId}/students/{studentId}/grades",
    operation_id="getStudentGrades",
    response_model=GradeReport,
    summary="A student's grade report. The class professor sees drafts; a student only their own.",
)
def get_student_grades(
    offering_id: OfferingId,
    student_id: Annotated[int, Path(alias="studentId", ge=1, le=2147483647)],
    actor: ActorDep,
    service: GradingServiceDep,
):
    return service.get_student_grades(actor=actor, offering_id=offering_id, student_id=student_id)


@router.post(
    "/submissions/{submissionId}/grade-record",
    operation_id="createInitialGrade",
    response_model=GradeRecord,
    summary="Professor saves a draft grade (score or special mark 11/12) for a submission.",
    responses={422: {"description": "INVALID_GRADE"}},
)
def create_initial_grade(
    submission_id: Annotated[int, Path(alias="submissionId", ge=1, le=2147483647)],
    body: GradeRequest,
    actor: MutationActorDep,
    service: GradingServiceDep,
):
    return service.save_draft(
        actor=actor,
        submission_id=submission_id,
        score=body.score,
        special_mark=_mark(body.specialMark),
        feedback=body.feedback,
        expected_submission_version=body.expectedSubmissionVersion,
        source_version_no=body.sourceVersionNo,
        reason=body.reason,
        zero_reason=body.zeroReason,
    )


@router.post(
    "/assignments/{assignmentId}/missing-work-decisions",
    operation_id="confirmMissingWork",
    response_model=GradeRecord,
    summary="Professor gives a student who did not submit a special mark (11 absent, 12 banned).",
    responses={409: {"description": "ALREADY_SUBMITTED"}},
)
def confirm_missing_work(
    assignment_id: AssignmentId,
    body: MissingWorkRequest,
    actor: MutationActorDep,
    service: GradingServiceDep,
):
    return service.record_missing_work(
        actor=actor,
        assignment_id=assignment_id,
        student_id=body.studentId,
        special_mark=_mark(body.specialMark),
        feedback=body.feedback,
        zero_reason=body.zeroReason,
    )


@router.put(
    "/assignments/{assignmentId}/grade-release",
    operation_id="releaseGrades",
    response_model=GradeRelease,
    summary="Professor releases every saved grade of the assignment to the class.",
)
def release_grades(
    assignment_id: AssignmentId, actor: MutationActorDep, service: GradingServiceDep
):
    return service.release_grades(actor=actor, assignment_id=assignment_id)


@router.get(
    "/offerings/{offeringId}/gradebook",
    operation_id="getCourseGradebook",
    response_model=Gradebook,
    summary="Class professor: every student x every grade item, with totals.",
)
def get_course_gradebook(
    offering_id: OfferingId,
    actor: ActorDep,
    service: GradingServiceDep,
    search: str | None = None,
    state: str = "ALL",
    activityId: int | None = None,
):
    return service.get_gradebook(
        actor=actor, offering_id=offering_id, search=search, state=state, activity_id=activityId
    )


@router.get(
    "/offerings/{offeringId}/gradebook.csv",
    operation_id="exportGradebookCsv",
    response_class=Response,
    summary="Class professor: the gradebook as a CSV file (special grades as 11 / 12).",
    responses={200: {"content": {"text/csv": {"schema": {"type": "string"}}}}},
)
def export_gradebook_csv(
    offering_id: OfferingId,
    actor: ActorDep,
    service: GradingServiceDep,
    search: str | None = None,
    state: str = "ALL",
    activityId: int | None = None,
):
    name, text = service.export_gradebook_csv(
        actor=actor, offering_id=offering_id, search=search, state=state, activity_id=activityId
    )
    return Response(
        content="\ufeff" + text,  # BOM so Excel reads accents correctly
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# ------------------------------------------------ contract operations not used yet
GradeRecordId = Annotated[int, Path(alias="gradeRecordId", ge=1, le=2147483647)]


@router.get(
    "/assignments/{assignmentId}/grade-records",
    operation_id="listAssignmentGradeRecords",
    response_model=AssignmentGradeRecords,
    summary="Class professor: every student's grade box for one assignment.",
)
def list_assignment_grade_records(
    assignment_id: AssignmentId, actor: ActorDep, service: GradingServiceDep
):
    return service.list_assignment_grade_records(actor=actor, assignment_id=assignment_id)


@router.get(
    "/grade-records/{gradeRecordId}",
    operation_id="getGradeRecord",
    response_model=GradeRecord,
    summary="One grade: draft, released version and edit history (history: professor only).",
)
def get_grade_record(grade_id: GradeRecordId, actor: ActorDep, service: GradingServiceDep):
    return service.get_grade_record(actor=actor, grade_record_id=grade_id)


@router.post(
    "/grade-records/{gradeRecordId}/revisions",
    operation_id="createGradeRevision",
    status_code=201,
    response_model=GradeRecord,
    summary="Change a grade (a new draft; same rules as saving a grade box).",
    responses={422: {"description": "INVALID_GRADE"}},
)
def create_grade_revision(
    grade_id: GradeRecordId,
    body: GradeRequest,
    actor: MutationActorDep,
    service: GradingServiceDep,
    version: VersionDep,
):
    return service.revise(
        actor=actor,
        grade_record_id=grade_id,
        expected_version=version,
        score=body.score,
        special_mark=_mark(body.specialMark),
        feedback=body.feedback,
        expected_submission_version=body.expectedSubmissionVersion,
        source_version_no=body.sourceVersionNo,
        reason=body.reason,
        zero_reason=body.zeroReason,
    )


@router.put(
    "/grade-records/{gradeRecordId}/publication",
    operation_id="publishGradeRevision",
    response_model=GradeRecord,
    summary="Release this one grade now (the rest of the assignment stays draft).",
)
def publish_grade_revision(
    grade_id: GradeRecordId,
    body: PublishGradeRequest,
    version: VersionDep,
    actor: MutationActorDep,
    service: GradingServiceDep,
):
    return service.publish(
        actor=actor, grade_record_id=grade_id, expected_version=version, revision_no=body.revisionNo
    )


@router.put(
    "/offerings/{offeringId}/gradebook/weights",
    operation_id="updateGradebookWeights",
    status_code=204,
)
def update_weights(
    offering_id: OfferingId,
    body: GradebookWeights,
    actor: MutationActorDep,
    version: VersionDep,
    service: GradingServiceDep,
):
    service.update_weights(
        actor=actor,
        offering_id=offering_id,
        expected_version=version,
        values=[v.model_dump() for v in body.values],
    )
    return Response(status_code=204)
