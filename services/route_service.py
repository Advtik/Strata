import re

from core.repository import (
    create_route_repo,
    get_routes_repo,
    get_project_owner,
    delete_route_repo,
    get_route_owner,
    get_route_by_id
)

from core.redis_cleanup import (
    cleanup_route
)


async def create_route_service(user, project_id, data):

    # 🔐 Step 1: Auth check
    if user is None:
        raise Exception("Not authenticated")

    # 🔐 Step 2: Ownership check
    owner = await get_project_owner(project_id)

    if not owner or owner["user_id"] != user["id"]:
        raise Exception("Not allowed")

    # 🧠 Step 3: Extract data
    name = data.get("name")

    if not name:
        raise Exception("Name required")

    # 🧠 Step 4: Validate name (URL-safe)
    if not re.match(r'^[a-zA-Z0-9\-]+$', name):
        raise Exception("Invalid route name")

    if len(name) > 50:
        raise Exception("Name too long")

    # 🚀 Step 5: Create route
    try:
        return await create_route_repo(project_id, name)
    except:
        raise Exception("Route Already Exists")


async def get_routes_service(user, project_id):

    if user is None:
        raise Exception("Not authenticated")

    owner = await get_project_owner(project_id)

    if not owner or owner["user_id"] != user["id"]:
        raise Exception("Not allowed")

    return await get_routes_repo(project_id)


async def delete_route_service(user, route_id):

    if user is None:
        raise Exception("Not authenticated")

    owner = await get_route_owner(route_id)

    if not owner or owner["user_id"] != user["id"]:
        raise Exception("Not allowed")
    
    route = await get_route_by_id(route_id)

    tenant_id = route["tenant_id"]

    # 🔥 CLEANUP
    cleanup_route(tenant_id, route_id)

    await delete_route_repo(route_id)