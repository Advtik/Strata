from core.redis_client import r


# ----------------------------
# BACKEND CLEANUP
# ----------------------------
def cleanup_backend(route_id: int, backend_id: int):
    r.delete(f"backend:{route_id}:{backend_id}")
    r.delete(f"cb:{route_id}:{backend_id}")
    r.delete(f"health:{route_id}:{backend_id}")


# ----------------------------
# ROUTE CLEANUP
# ----------------------------
def cleanup_route(tenant_id: int, route_id: int):

    # delete backend-related keys
    for key in r.scan_iter(f"backend:{route_id}:*"):
        r.delete(key)

    for key in r.scan_iter(f"cb:{route_id}:*"):
        r.delete(key)

    for key in r.scan_iter(f"health:{route_id}:*"):
        r.delete(key)

    # delete route metrics
    r.delete(f"metrics:{tenant_id}:{route_id}")
    r.delete(f"metrics_ts:{tenant_id}:{route_id}")


# ----------------------------
# PROJECT (TENANT) CLEANUP
# ----------------------------
def cleanup_project(tenant_id: int, route_ids: list[int]):

    for route_id in route_ids:

        # backend-level cleanup
        for key in r.scan_iter(f"backend:{route_id}:*"):
            r.delete(key)

        for key in r.scan_iter(f"cb:{route_id}:*"):
            r.delete(key)

        for key in r.scan_iter(f"health:{route_id}:*"):
            r.delete(key)

        # route-level metrics
        r.delete(f"metrics:{tenant_id}:{route_id}")
        r.delete(f"metrics_ts:{tenant_id}:{route_id}")