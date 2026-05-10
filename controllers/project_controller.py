from fastapi import Request, HTTPException
from services.project_service import (
    create_project_service,
    get_projects_service
)


async def create_project_controller(request: Request):
    user = request.state.user

    try:
        data = await request.json()
        project = await create_project_service(user, data)

        return {
            "id": project["id"],
            "name": project["name"]
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


async def get_projects_controller(request: Request):
    user = request.state.user

    try:
        projects = await get_projects_service(user)

        return projects

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))