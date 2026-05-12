import re

from core.repository import (
    create_route_repo,
    get_routes_repo,
    get_project_owner,
    delete_route_repo,
    get_route_owner,
    get_route_by_id,
    get_route_backends,
    get_route_backends_count
)

from core.redis_cleanup import (
    cleanup_route
)

from core.redis_client import r

from services.metrics_service import (
    get_route_metrics_service,
    get_backends_metrics_service
)

from services.rate_limit_service import (
    get_route_rate_limit_service
)

from core.health import (
    is_backend_healthy
)

from core.circuit import (
    get_state
)


async def create_route_service(
    user,
    project_id,
    data
):

    if user is None:

        raise Exception(
            "Not authenticated"
        )

    owner = await get_project_owner(
        project_id
    )

    if (
        not owner
        or owner["user_id"] != user["id"]
    ):

        raise Exception(
            "Not allowed"
        )

    name = data.get("name")

    if not name:

        raise Exception(
            "Name required"
        )

    if not re.match(
        r"^[a-zA-Z0-9\-]+$",
        name
    ):

        raise Exception(
            "Invalid route name"
        )

    if len(name) > 50:

        raise Exception(
            "Name too long"
        )

    try:

        return await create_route_repo(
            project_id,
            name
        )

    except Exception:

        raise Exception(
            "Route Already Exists"
        )


async def get_routes_service(
    user,
    project_id
):

    if user is None:

        raise Exception(
            "Not authenticated"
        )

    owner = await get_project_owner(
        project_id
    )

    if (
        not owner
        or owner["user_id"] != user["id"]
    ):

        raise Exception(
            "Not allowed"
        )

    routes = await get_routes_repo(
        project_id
    )

    enriched_routes = []

    for route in routes:

        backends = await get_route_backends(
            route["id"]
        )

        backend_count = (
            await get_route_backends_count(
                route["id"]
            )
        )

        healthy_count = 0
        unhealthy_count = 0

        for backend in backends:

            backend_id = backend["id"]

            health_key = (
                f"health:{route['id']}:{backend_id}"
            )

            health = await r.hgetall(
                health_key
            )

            if health:

                is_healthy = int(
                    health.get(
                        "healthy",
                        0
                    )
                )

                if is_healthy == 1:

                    healthy_count += 1

                else:

                    unhealthy_count += 1

            else:

                unhealthy_count += 1

        if healthy_count == 0:

            status = "offline"

        elif healthy_count == backend_count:

            status = "healthy"

        elif healthy_count > 0:

            status = "degraded"

        else:

            status = "offline"

        metrics_key = (
            f"metrics:{project_id}:{route['id']}"
        )

        metrics = await r.hgetall(
            metrics_key
        )

        total_requests = 0
        total_latency = 0
        avg_latency = 0

        if metrics:

            total_requests = int(
                metrics.get(
                    "total_requests",
                    0
                )
            )

            total_latency = round(
                float(
                    metrics.get(
                        "total_latency",
                        0
                    )
                ),
                2
            )

            avg_latency = (
                0
                if total_requests == 0
                else (
                    total_latency /
                    total_requests
                )
            )

        enriched_routes.append({

            "id": route["id"],

            "name": route["name"],

            "path": f"/{route['name']}",

            "backends": backend_count,

            "requests": total_requests,

            "avg_latency": avg_latency,

            "status": status,

            "created_at": str(
                route["created_at"]
            )
        })

    return enriched_routes


async def delete_route_service(
    user,
    route_id
):

    if user is None:

        raise Exception(
            "Not authenticated"
        )

    owner = await get_route_owner(
        route_id
    )

    if (
        not owner
        or owner["user_id"] != user["id"]
    ):

        raise Exception(
            "Not allowed"
        )

    route = await get_route_by_id(
        route_id
    )

    tenant_id = route["tenant_id"]

    await cleanup_route(
        tenant_id,
        route_id
    )

    await delete_route_repo(
        route_id
    )


async def get_route_detail_service(
    user,
    route_id
):

    if user is None:

        raise Exception(
            "Not authenticated"
        )

    owner = await get_route_owner(
        route_id
    )

    if (
        not owner
        or owner["user_id"] != user["id"]
    ):

        raise Exception(
            "Not allowed"
        )

    tenant_id = owner["tenant_id"]

    route = await get_route_by_id(
        route_id
    )

    route_metrics = (
        await get_route_metrics_service(
            tenant_id,
            route_id
        )
    )

    rate_limit = (
        await get_route_rate_limit_service(
            user,
            route_id
        )
    )

    backend_configs = (
        await get_route_backends(
            route_id
        )
    )

    backend_metrics = (
        await get_backends_metrics_service(
            route_id
        )
    )

    metrics_map = {
        b["backend_id"]: b
        for b in backend_metrics["backends"]
    }

    enriched_backends = []

    for backend in backend_configs:

        backend_id = backend["id"]

        metrics = metrics_map.get(
            backend_id,
            {}
        )

        healthy = await is_backend_healthy(
            route_id,
            backend_id
        )

        circuit = await get_state(
            route_id,
            backend_id
        )

        enriched_backends.append({

            "id": backend_id,

            "url": backend["url"],

            "created_at": str(
                backend["created_at"]
            ),

            "status": (
                "healthy"
                if healthy
                else "offline"
            ),

            "circuit_state":
                circuit["state"],

            "last_circuit_opened":
                circuit["opened_at"],

            "requests":
                metrics.get(
                    "requests",
                    0
                ),

            "successes":
                metrics.get(
                    "successes",
                    0
                ),

            "failures":
                metrics.get(
                    "failures",
                    0
                ),

            "avg_latency":
                metrics.get(
                    "avg_latency",
                    0
                )
        })

    return {

        "id": route["id"],

        "name": route["name"],

        "path": f"/{route['name']}",

        "requests":
            route_metrics["total_requests"],

        "avg_latency":
            route_metrics["avg_latency"],

        "capacity":
            rate_limit["capacity"]
            if rate_limit else 0,

        "refill_rate":
            rate_limit["refill_rate"]
            if rate_limit else 0,

        "monitoring": {

            **route_metrics,

            "rate_limit_threshold":
                rate_limit["capacity"]
                if rate_limit else 0
        },

        "backends":
            enriched_backends
    }