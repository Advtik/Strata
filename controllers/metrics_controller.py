from fastapi import Request, HTTPException
from services.metrics_service import (
    get_route_metrics_service,
    get_backends_metrics_service
)
from core.repository import get_route_owner


async def get_route_metrics_controller(request: Request, route_id: int):

    user = request.state.user

    if user is None:
        raise HTTPException(401, "Unauthorized")

    owner = await get_route_owner(route_id)

    if not owner or owner["user_id"] != user["id"]:
        raise HTTPException(403, "Forbidden")

    tenant_id = owner["tenant_id"]

    return await get_route_metrics_service(tenant_id, route_id)


async def get_backends_metrics_controller(request: Request, route_id: int):

    user = request.state.user

    if user is None:
        raise HTTPException(401, "Unauthorized")

    owner = await get_route_owner(route_id)

    if not owner or owner["user_id"] != user["id"]:
        raise HTTPException(403, "Forbidden")

    return await get_backends_metrics_service(route_id)