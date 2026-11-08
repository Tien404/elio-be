from typing import Annotated, Literal

from fastapi import APIRouter, File, Path, Query, UploadFile
from fastapi.responses import FileResponse

from app.api.dependencies import (
    ActorDep,
    ContentServiceDep,
    MutationActorDep,
    SubmissionServiceDep,
)
from app.api.schemas.content import FileAsset

router = APIRouter(tags=["files"], responses={400: {"description": "Invalid request"}})


@router.post(
    "/files",
    operation_id="prepareFile",
    status_code=201,
    response_model=FileAsset,
    summary="Upload step 1: store a file for a class (then attach it within 24h).",
    responses={413: {"description": "FILE_TOO_LARGE"}},
)
def prepare_file(
    file: Annotated[UploadFile, File()],
    actor: MutationActorDep,
    service: ContentServiceDep,
    submissions: SubmissionServiceDep,
    offering_id: Annotated[int, Query(alias="offeringId", ge=1, le=2147483647)],
    purpose: Literal["MATERIAL", "ASSIGNMENT_ATTACHMENT", "SUBMISSION"] = "MATERIAL",
    assignment_id: Annotated[
        int | None,
        Query(alias="assignmentId", ge=1, le=2147483647, description="For SUBMISSION"),
    ] = None,
):
    if purpose == "SUBMISSION":
        return submissions.prepare_file(
            actor=actor,
            offering_id=offering_id,
            assignment_id=assignment_id,
            file_name=file.filename,
            content_type=file.content_type,
            stream=file.file,
        )
    return service.prepare_file(
        actor=actor,
        offering_id=offering_id,
        purpose=purpose,
        file_name=file.filename,
        content_type=file.content_type,
        stream=file.file,
    )


@router.get(
    "/files/{fileId}/content",
    operation_id="downloadFile",
    response_class=FileResponse,
    responses={200: {"content": {"application/octet-stream": {}}}},
    summary="Download a file you may see (always as an attachment).",
)
def download_file(
    file_id: Annotated[int, Path(alias="fileId", ge=1, le=2147483647)],
    actor: ActorDep,
    service: ContentServiceDep,
):
    download = service.download_file(actor=actor, file_id=file_id)
    return FileResponse(
        download.path,
        media_type=download.mime_type,
        filename=download.file_name,
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )
