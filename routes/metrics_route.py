from fastapi import APIRouter, Request
from controllers.metrics_controller import (
    get_route_metrics_controller,
    get_backends_metrics_controller,
    get_projects_overview_controller
)

router = APIRouter()


@router.get("/route/{route_id}")
async def get_route_metrics(request: Request, route_id: int):
    return await get_route_metrics_controller(request, route_id)


@router.get("/backends/{route_id}")
async def get_backends_metrics(request: Request, route_id: int):
    return await get_backends_metrics_controller(request, route_id)

router.get("/projects")(
    get_projects_overview_controller
)