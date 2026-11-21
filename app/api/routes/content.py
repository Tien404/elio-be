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
    Announcement,
    AnnouncementPage,
    AnnouncementRequest,
    Resource,
    ResourcePage,
    ResourceRequest,
    Topic,
    TopicPage,
    TopicRequest,
    UpdateResourceRequest,
)

router = APIRouter(tags=["content"], responses={400: {"description": "Invalid request"}})

OfferingId = Annotated[int, Path(alias="offeringId", ge=1, le=2147483647)]
ResourceId = Annotated[int, Path(alias="resourceId", ge=1, le=2147483647)]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


@router.get(
    "/offerings/{offeringId}/announcements",
    operation_id="listAnnouncements",
    response_model=AnnouncementPage,
    summary="Class announcements, newest first.",
)
def list_announcements(
    offeringId: Annotated[int, Path(ge=1, le=2147483647)],
    actor: ActorDep,
    service: ContentServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    pageSize: Annotated[int, Query(ge=1, le=100)] = 25,
):
    return service.list_announcements(
        actor=actor, offering_id=offeringId, page=page, page_size=pageSize
    )


@router.post(
    "/offerings/{offeringId}/announcements",
    operation_id="createAnnouncement",
    status_code=201,
    response_model=Announcement,
    summary="Professor posts an announcement; class members get it in their inbox.",
)
def create_announcement(
    offeringId: Annotated[int, Path(ge=1, le=2147483647)],
    body: AnnouncementRequest,
    actor: MutationActorDep,
    service: ContentServiceDep,
):
    return service.create_announcement(
        actor=actor, offering_id=offeringId, title=body.title, body=body.body
    )


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
        data=body.model_dump(),
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
        changes=body.model_dump(exclude_unset=True),
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


@router.patch("/topics/{topicId}", operation_id="updateTopic", response_model=Topic)
def update_topic(
    topicId: Annotated[int, Path(ge=1, le=2147483647)],
    body: TopicRequest,
    actor: MutationActorDep,
    version: VersionDep,
    service: ContentServiceDep,
):
    return service.update_topic(
        actor=actor,
        topic_id=topicId,
        expected_version=version,
        title=body.title,
        position=body.position,
    )
