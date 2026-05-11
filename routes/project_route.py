from fastapi import APIRouter, Request
from controllers.project_controller import (
    create_project_controller,
    delete_project_controller,
    get_projects_controller
)

router = APIRouter()


@router.post("/")
async def create_project(request: Request):
    return await create_project_controller(request)


@router.get("/")
async def get_projects(request: Request):
    return await get_projects_controller(request)

@router.delete("/{project_id}")
async def delete_project(request: Request, project_id: int):
    return await delete_project_controller(request, project_id)