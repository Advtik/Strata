from core.repository import create_project_repo, get_projects_repo


async def create_project_service(user, data):
    if user is None:
        raise Exception("Not authenticated")

    name = data.get("name")

    if not name:
        raise Exception("Project name required")

    if len(name) > 50:
        raise Exception("Name too long")

    return await create_project_repo(user["id"], name)


async def get_projects_service(user):
    if user is None:
        raise Exception("Not authenticated")

    return await get_projects_repo(user["id"])