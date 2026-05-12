import json

from core.redis_client import r
from db.connect import db

from core.repository import (
    get_user_routes_with_tenants
)


async def get_route_metrics_service(
    tenant_id: int,
    route_id: int
):

    key = f"metrics:{tenant_id}:{route_id}"

    ts_key = (
        f"metrics_ts:{tenant_id}:{route_id}"
    )

    data = await r.hgetall(key)

    def to_int(x):

        return int(x or 0)

    def to_float(x):

        return float(x or 0)

    total_requests = to_int(
        data.get("total_requests")
    )

    allowed = to_int(
        data.get("allowed_requests")
    )

    blocked = to_int(
        data.get("blocked_requests")
    )

    failures = to_int(
        data.get("backend_failures")
    )

    total_latency = to_float(
        data.get("total_latency")
    )

    avg_latency = (
        total_latency / allowed
        if allowed > 0
        else 0
    )

    raw_ts = await r.lrange(
        ts_key,
        0,
        -1
    )

    timestamps = [
        json.loads(t)
        for t in raw_ts
    ]

    minute_buckets = {}

    for entry in timestamps:

        minute = (
            entry["time"] -
            (entry["time"] % 60)
        )

        if minute not in minute_buckets:

            minute_buckets[minute] = 0

        minute_buckets[minute] += (
            entry["count"]
        )

    timeline = [
        {
            "time": t,
            "count": c
        }
        for t, c in sorted(
            minute_buckets.items()
        )
    ]

    timeline = timeline[-60:]

    return {
        "route_id": route_id,
        "total_requests": total_requests,
        "allowed_requests": allowed,
        "blocked_requests": blocked,
        "backend_failures": failures,
        "avg_latency": avg_latency,
        "timeline": timeline
    }


async def get_backends_metrics_service(
    route_id: int
):

    keys = []

    async for key in r.scan_iter(
        f"backend:{route_id}:*"
    ):

        keys.append(key)

    result = []

    for key in keys:

        key_str = (
            key
            if isinstance(key, str)
            else key.decode()
        )

        _, r_id, backend_id = key_str.split(":")

        data = await r.hgetall(key)

        result.append({
            "backend_id": int(backend_id),
            "requests": int(
                data.get("requests", 0)
            ),
            "successes": int(
                data.get("successes", 0)
            ),
            "failures": int(
                data.get("failures", 0)
            ),
            "recent_requests": float(
                data.get(
                    "recent_requests",
                    0.0
                )
            ),
            "avg_latency": float(
                data.get(
                    "avg_latency",
                    0
                )
            )
        })

    return {
        "route_id": route_id,
        "backends": result
    }


async def get_projects_overview_service(
    user_id: int
):

    routes = await get_user_routes_with_tenants(
        user_id
    )

    total_requests = 0
    blocked_requests = 0
    total_latency = 0

    healthy_backends = 0
    total_backends = 0

    for route in routes:

        route_id = route["route_id"]

        tenant_id = route["tenant_id"]

        metrics_key = (
            f"metrics:{tenant_id}:{route_id}"
        )

        metrics = await r.hgetall(
            metrics_key
        )

        route_requests = int(
            metrics.get(
                "total_requests",
                0
            )
        )

        route_blocked = int(
            metrics.get(
                "blocked_requests",
                0
            )
        )

        route_latency = float(
            metrics.get(
                "total_latency",
                0
            )
        )

        total_requests += route_requests

        blocked_requests += route_blocked

        total_latency += route_latency

        health_keys = await r.keys(
            f"health:{route_id}:*"
        )

        total_backends += len(
            health_keys
        )

        for key in health_keys:

            healthy = await r.hget(
                key,
                "healthy"
            )

            if healthy == "1":

                healthy_backends += 1

    allowed_requests = (
        total_requests -
        blocked_requests
    )

    avg_latency = (
        total_latency / allowed_requests
        if allowed_requests > 0
        else 0
    )

    return {
        "total_requests": total_requests,
        "avg_latency": round(
            avg_latency * 1000,
            2
        ),
        "healthy_backends": healthy_backends,
        "total_backends": total_backends,
        "blocked_requests": blocked_requests
    }