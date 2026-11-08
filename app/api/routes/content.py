from typing import Annotated

from fastapi import APIRouter, Path, Query, Response

from app.api.dependencies import (
    ActorDep,
    ContentServiceDep,
    MutationActorDep,
    VersionDep,
    set_etag,
)
from app.api.schemas.content import (
    Resource,
    ResourcePage,
    ResourceRequest,
    Topic,
    TopicPage,
    TopicRequest,
    UpdateResourceRequest,
)
from app.services.content_service import ContentService

router = APIRouter(tags=["content"], responses={400: {"description": "Invalid request"}})

OfferingId = Annotated[int, Path(alias="offeringId", ge=1, le=2147483647)]
ResourceId = Annotated[int, Path(alias="resourceId", ge=1, le=2147483647)]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


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


@router.get(
    "/offerings/{offeringId}/resources",
    operation_id="listResources",
    response_model=ResourcePage,
    summary="Class materials in topic order; students see PUBLISHED only.",
)
def list_resources(
    offering_id: OfferingId,
    actor: ActorDep,
    service: ContentServiceDep,
    page: Page = 1,
    pageSize: PageSize = 50,
):
    return service.list_materials(
        actor=actor, offering_id=offering_id, page=page, page_size=pageSize
    )


@router.post(
    "/offerings/{offeringId}/resources",
    operation_id="createResource",
    status_code=201,
    response_model=Resource,
    summary="Class professor adds a FILE (from POST /files) or LINK material to a topic.",
    responses={422: {"description": "TOPIC_NOT_FOUND / FILE_NOT_USABLE"}},
)
def create_resource(
    offering_id: OfferingId,
    body: ResourceRequest,
    actor: MutationActorDep,
    response: Response,
    service: ContentServiceDep,
):
    view = service.save_material(
        actor=actor,
        offering_id=offering_id,
        topic_id=body.topicId,
        kind=body.kind,
        title=body.title,
        status=body.status,
        external_url=body.externalUrl,
        file_ids=body.fileIds,
    )
    response.headers["Location"] = f"/api/v1/resources/{view['id']}"
    set_etag(response, view["version"])
    return view


@router.get("/resources/{resourceId}", operation_id="getResource", response_model=Resource)
def get_resource(
    resource_id: ResourceId, actor: ActorDep, response: Response, service: ContentServiceDep
):
    view = service.get_material(actor=actor, material_id=resource_id)
    set_etag(response, view["version"])
    return view


@router.patch(
    "/resources/{resourceId}",
    operation_id="updateResource",
    response_model=Resource,
    summary="Rename and/or publish a material (status PUBLISHED). Needs If-Match.",
    responses={412: {"description": "VERSION_CONFLICT"}},
)
def update_resource(
    resource_id: ResourceId,
    body: UpdateResourceRequest,
    actor: MutationActorDep,
    version: VersionDep,
    response: Response,
    service: ContentServiceDep,
):
    view = service.update_material(
        actor=actor,
        material_id=resource_id,
        expected_version=version,
        title=body.title,
        status=body.status,
    )
    set_etag(response, view["version"])
    return view


@router.get("/offerings/{offeringId}/topics", operation_id="listTopics", response_model=TopicPage)
def list_topics(
    offering_id: OfferingId,
    actor: ActorDep,
    service: ContentServiceDep,
    page: Page = 1,
    pageSize: PageSize = 50,
):
    return service.list_topics(actor=actor, offering_id=offering_id, page=page, page_size=pageSize)


@router.post(
    "/offerings/{offeringId}/topics",
    operation_id="createTopic",
    status_code=201,
    response_model=Topic,
    summary="Class professor adds a topic (e.g. Week 1).",
    responses={409: {"description": "POSITION_TAKEN"}},
)
def create_topic(
    offering_id: OfferingId,
    body: TopicRequest,
    actor: MutationActorDep,
    service: ContentServiceDep,
):
    return service.create_topic(
        actor=actor, offering_id=offering_id, title=body.title, position=body.position
    )


@router.patch("/topics/{topicId}", operation_id="updateTopic", status_code=501)
def update_topic(topicId: int = Path(ge=1, le=2147483647)):
    return ContentService().update_topic(topic_id=topicId)
