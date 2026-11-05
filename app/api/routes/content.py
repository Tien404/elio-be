from fastapi import APIRouter, Path

from app.services.content_service import ContentService

router = APIRouter(tags=["content"], responses={400: {"description": "Invalid request"}})


@router.get(
    "/offerings/{offeringId}/announcements", operation_id="listAnnouncements", status_code=501
)
def list_announcements(offeringId: int = Path(ge=1, le=2147483647)):
    return ContentService().list_announcements(offering_id=offeringId)


@router.post(
    "/offerings/{offeringId}/announcements", operation_id="createAnnouncement", status_code=501
)
def create_announcement(offeringId: int = Path(ge=1, le=2147483647)):
    return ContentService().create_announcement(offering_id=offeringId)


@router.get("/offerings/{offeringId}/resources", operation_id="listResources", status_code=501)
def list_resources(offeringId: int = Path(ge=1, le=2147483647)):
    return ContentService().list_resources(offering_id=offeringId)


@router.post("/offerings/{offeringId}/resources", operation_id="createResource", status_code=501)
def create_resource(offeringId: int = Path(ge=1, le=2147483647)):
    return ContentService().save_material(offering_id=offeringId)


@router.get("/resources/{resourceId}", operation_id="getResource", status_code=501)
def get_resource(resourceId: int = Path(ge=1, le=2147483647)):
    return ContentService().read_material(resource_id=resourceId)


@router.patch("/resources/{resourceId}", operation_id="updateResource", status_code=501)
def update_resource(resourceId: int = Path(ge=1, le=2147483647)):
    return ContentService().update_resource(resource_id=resourceId)


@router.get("/offerings/{offeringId}/topics", operation_id="listTopics", status_code=501)
def list_topics(offeringId: int = Path(ge=1, le=2147483647)):
    return ContentService().list_topics(offering_id=offeringId)


@router.post("/offerings/{offeringId}/topics", operation_id="createTopic", status_code=501)
def create_topic(offeringId: int = Path(ge=1, le=2147483647)):
    return ContentService().create_topic(offering_id=offeringId)


@router.patch("/topics/{topicId}", operation_id="updateTopic", status_code=501)
def update_topic(topicId: int = Path(ge=1, le=2147483647)):
    return ContentService().update_topic(topic_id=topicId)
