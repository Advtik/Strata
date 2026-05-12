from core.redis_client import r


# ----------------------------
# BACKEND CLEANUP
# ----------------------------
async def cleanup_backend(
    route_id: int,
    backend_id: int
):

    await r.delete(
        f"backend:{route_id}:{backend_id}"
    )

    await r.delete(
        f"cb:{route_id}:{backend_id}"
    )

    await r.delete(
        f"health:{route_id}:{backend_id}"
    )


# ----------------------------
# ROUTE CLEANUP
# ----------------------------
async def cleanup_route(
    tenant_id: int,
    route_id: int
):

    async for key in r.scan_iter(
        f"backend:{route_id}:*"
    ):

        await r.delete(key)

    async for key in r.scan_iter(
        f"cb:{route_id}:*"
    ):

        await r.delete(key)

    async for key in r.scan_iter(
        f"health:{route_id}:*"
    ):

        await r.delete(key)

    await r.delete(
        f"metrics:{tenant_id}:{route_id}"
    )

    await r.delete(
        f"metrics_ts:{tenant_id}:{route_id}"
    )


# ----------------------------
# PROJECT (TENANT) CLEANUP
# ----------------------------
async def cleanup_project(
    tenant_id: int,
    route_ids: list[int]
):

    for route_id in route_ids:

        async for key in r.scan_iter(
            f"backend:{route_id}:*"
        ):

            await r.delete(key)

        async for key in r.scan_iter(
            f"cb:{route_id}:*"
        ):

            await r.delete(key)

        async for key in r.scan_iter(
            f"health:{route_id}:*"
        ):

            await r.delete(key)

        await r.delete(
            f"metrics:{tenant_id}:{route_id}"
        )

        await r.delete(
            f"metrics_ts:{tenant_id}:{route_id}"
        )