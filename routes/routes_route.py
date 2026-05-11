from fastapi import APIRouter, Request

from controllers.route_controller import (
    create_route_controller,
    get_routes_controller,
    delete_route_controller,
    get_route_detail_controller
)

router = APIRouter()


@router.post("/{project_id}")
async def create_route(request: Request, project_id: int):
    return await create_route_controller(request, project_id)

@router.get("/detail/{route_id}")
async def get_route_detail(
    request: Request,
    route_id: int
):
    return await get_route_detail_controller(
        request,
        route_id
    )

@router.get("/{project_id}")
async def get_routes(request: Request, project_id: int):
    return await get_routes_controller(request, project_id)

@router.delete("/{route_id}")
async def delete_route(request: Request, route_id: int):
    return await delete_route_controller(request, route_id)
