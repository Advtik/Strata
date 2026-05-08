from fastapi import APIRouter, Request

from controllers.backend_controller import (
    create_backend_controller,
    get_backends_controller,
    delete_backend_controller
)

router = APIRouter()


@router.post("/{route_id}")
async def create_backend(request: Request, route_id: int):
    return await create_backend_controller(request, route_id)


@router.get("/{route_id}")
async def get_backends(request: Request, route_id: int):
    return await get_backends_controller(request, route_id)


@router.delete("/{backend_id}")
async def delete_backend(request: Request, backend_id: int):
    return await delete_backend_controller(request, backend_id)