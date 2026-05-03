from fastapi import APIRouter, Request
from controllers.project_controller import (
    create_project_controller,
    get_projects_controller
)

router = APIRouter()


@router.post("/")
async def create_project(request: Request):
    return await create_project_controller(request)


@router.get("/")
async def get_projects(request: Request):
    return await get_projects_controller(request)