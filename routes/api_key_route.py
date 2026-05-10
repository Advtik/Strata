from fastapi import APIRouter, Request
from controllers.api_key_controller import (
    create_api_key_controller,
    get_api_keys_controller,
    delete_api_key_controller
)

router = APIRouter()


@router.post("/{project_id}")
async def create_key(request: Request, project_id: int,):
    return await create_api_key_controller(request, project_id)


@router.get("/{project_id}")
async def get_keys(request: Request, project_id: int):
    return await get_api_keys_controller(request, project_id)


@router.delete("/{key_id}")
async def delete_key(request: Request, key_id: int):
    return await delete_api_key_controller(request, key_id)