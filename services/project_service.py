from core.repository import create_project_repo, get_projects_repo, delete_project_repo, get_project_owner, get_backends_count_for_project
from core.redis_cleanup import cleanup_project
from core.redis_client import r


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

    projects = await get_projects_repo(user["id"])

    enriched_projects = []

    for project in projects:

        routes = await get_project_routes(project["id"])

        route_count = len(routes)

        backend_count = await get_backends_count_for_project(project["id"])

        total_requests = 0

        status = "healthy"

        for route in routes:

            route_id = route["id"]

            metrics_key = f"metrics:{project['id']}:{route_id}"

            metrics = await r.hgetall(metrics_key)

            if metrics:

                decoded = {
                    (k.decode() if isinstance(k, bytes) else k):
                    (v.decode() if isinstance(v, bytes) else v)
                    for k, v in metrics.items()
                }

                total_requests += int(decoded.get("total_requests", 0))

            health_keys = []

            async for key in r.scan_iter(
                f"health:{route_id}:*"
            ):

                health_keys.append(key)

            for health_key in health_keys:
                health_data = await r.hgetall(health_key)
                if not health_data:
                    continue

                is_healthy = health_data.get(b"healthy", health_data.get("healthy", b"1"))
                if isinstance(is_healthy, bytes):
                    is_healthy = is_healthy.decode()

                if is_healthy == "0":
                    status = "degraded"
                    break

            if status == "degraded":
                break


        enriched_projects.append({
            "id": project["id"],
            "name": project["name"],
            "created_at": str(project["created_at"]),
            "routes": route_count,
            "backends": backend_count,
            "requests": total_requests,
            "status": status
        })

    return enriched_projects

from core.redis_cleanup import cleanup_project
from core.repository import get_project_routes


async def delete_project_service(user, project_id):

    if user is None:
        raise Exception("Not authenticated")

    owner = await get_project_owner(project_id)

    if not owner or owner["user_id"] != user["id"]:
        raise Exception("Not allowed")

    routes = await get_project_routes(project_id)
    route_ids = [r["id"] for r in routes]

    await cleanup_project(project_id, route_ids)

    # DB delete
    await delete_project_repo(project_id)