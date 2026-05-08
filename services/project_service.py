from core.repository import create_project_repo, get_projects_repo, delete_project_repo, get_project_owner
from core.redis_cleanup import cleanup_project


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


from core.redis_cleanup import cleanup_project
from core.repository import get_project_routes


async def delete_project_service(user, project_id):

    if user is None:
        raise Exception("Not authenticated")

    owner = await get_project_owner(project_id)

    if not owner or owner["user_id"] != user["id"]:
        raise Exception("Not allowed")

    # 🔥 get all route_ids first
    routes = await get_project_routes(project_id)
    route_ids = [r["id"] for r in routes]

    # 🔥 CLEANUP
    cleanup_project(project_id, route_ids)

    # DB delete
    await delete_project_repo(project_id)