from fastapi import APIRouter, Request
from controllers.rate_limit_controller import (
    set_global_rate_limit_controller,
    set_route_rate_limit_controller,
    get_global_rate_limit_controller,
    get_route_rate_limit_controller
)

router = APIRouter()


@router.post("/global/{api_key_id}")
async def set_global(request: Request, api_key_id: int):
    return await set_global_rate_limit_controller(request, api_key_id)

@router.get("/global/{api_key_id}")
async def get_global(request: Request, api_key_id: int):
    return await get_global_rate_limit_controller(request, api_key_id)


@router.post("/route/{route_id}")
async def set_route(request: Request, route_id: int):
    return await set_route_rate_limit_controller(request, route_id)

@router.get("/route/{route_id}")
async def get_route(request: Request, route_id: int):
    return await get_route_rate_limit_controller(request, route_id)