from fastapi import APIRouter, Path

from app.services.content_service import ContentService

router = APIRouter(tags=["files"], responses={400: {"description": "Invalid request"}})


@router.post("/files", operation_id="prepareFile", status_code=501)
def prepare_file():
    return ContentService().prepare_file()


@router.get("/files/{fileId}/content", operation_id="downloadFile", status_code=501)
def download_file(fileId: int = Path(ge=1, le=2147483647)):
    return ContentService().download_file(file_id=fileId)
