from core.repository import (
    create_backend_repo,
    get_backends_repo,
    delete_backend_repo,
    get_backend_by_id,
    get_route_owner
)

from core.redis_cleanup import cleanup_backend


# ----------------------------
# CREATE BACKEND
# ----------------------------
async def create_backend_service(user, route_id, data):

    if user is None:
        raise Exception("Not authenticated")

    # 🔐 ownership check
    owner = await get_route_owner(route_id)

    if not owner or owner["user_id"] != user["id"]:
        raise Exception("Not allowed")

    url = data.get("url")

    if not url:
        raise Exception("URL required")

    # ✅ URL validation (basic)
    if not (url.startswith("http://") or url.startswith("https://")):
        raise Exception("Invalid URL")

    if len(url) > 200:
        raise Exception("URL too long")

    return await create_backend_repo(route_id, url)


# ----------------------------
# GET BACKENDS
# ----------------------------
async def get_backends_service(user, route_id):

    if user is None:
        raise Exception("Not authenticated")

    owner = await get_route_owner(route_id)

    if not owner or owner["user_id"] != user["id"]:
        raise Exception("Not allowed")

    return await get_backends_repo(route_id)


# ----------------------------
# DELETE BACKEND
# ----------------------------
async def delete_backend_service(user, backend_id):

    if user is None:
        raise Exception("Not authenticated")

    backend = await get_backend_by_id(backend_id)

    if not backend:
        raise Exception("Backend not found")

    route_id = backend["route_id"]

    # 🔐 ownership check via route
    owner = await get_route_owner(route_id)

    if not owner or owner["user_id"] != user["id"]:
        raise Exception("Not allowed")

    # 🔥 Redis cleanup FIRST
    cleanup_backend(route_id, backend_id)

    # DB delete
    await delete_backend_repo(backend_id)