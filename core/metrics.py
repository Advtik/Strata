import time
import json

from core.redis_client import r

RETENTION_SECONDS = 600


def _metrics_key(
    tenant_id,
    route_id
):

    return f"metrics:{tenant_id}:{route_id}"


def _timestamps_key(
    tenant_id,
    route_id
):

    return f"metrics_ts:{tenant_id}:{route_id}"


async def record_metric(
    tenant_id,
    route_id,
    latency,
    status
):

    current_time = int(
        time.time()
    )

    cutoff = (
        current_time -
        RETENTION_SECONDS
    )

    key = _metrics_key(
        tenant_id,
        route_id
    )

    ts_key = _timestamps_key(
        tenant_id,
        route_id
    )

    exists = await r.exists(key)

    if not exists:

        await r.hset(
            key,
            mapping={
                "total_requests": 0,
                "allowed_requests": 0,
                "blocked_requests": 0,
                "backend_failures": 0,
                "total_latency": 0.0
            }
        )

    await r.hincrby(
        key,
        "total_requests",
        1
    )

    last = await r.lindex(
        ts_key,
        -1
    )

    if last:

        last = json.loads(last)

    if (
        last and
        last["time"] == current_time
    ):

        last["count"] += 1

        await r.lset(
            ts_key,
            -1,
            json.dumps(last)
        )

    else:

        await r.rpush(
            ts_key,
            json.dumps({
                "time": current_time,
                "count": 1
            })
        )

    while True:

        first = await r.lindex(
            ts_key,
            0
        )

        if not first:

            break

        first = json.loads(first)

        if first["time"] >= cutoff:

            break

        await r.lpop(ts_key)

    if status == "blocked":

        await r.hincrby(
            key,
            "blocked_requests",
            1
        )

        return

    if status == "failure":

        await r.hincrby(
            key,
            "backend_failures",
            1
        )

    if status == "allowed":

        await r.hincrby(
            key,
            "allowed_requests",
            1
        )

    await r.hincrbyfloat(
        key,
        "total_latency",
        latency
    )


async def get_metrics():

    result = {
        "tenants": []
    }

    keys = await r.keys(
        "metrics:*"
    )

    tenant_map = {}

    for key in keys:

        key_str = (
            key.decode()
            if isinstance(key, bytes)
            else key
        )

        _, tenant_id, route_id = key_str.split(
            ":",
            2
        )

        data = await r.hgetall(key)

        def to_int(x):

            if x is None:

                return 0

            return int(
                x.decode()
                if isinstance(x, bytes)
                else x
            )

        def to_float(x):

            if x is None:

                return 0.0

            return float(
                x.decode()
                if isinstance(x, bytes)
                else x
            )

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

        ts_key = _timestamps_key(
            tenant_id,
            route_id
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

        bucketed_timestamps = [
            {
                "time": t,
                "count": c
            }
            for t, c in sorted(
                minute_buckets.items()
            )
        ]

        bucketed_timestamps = (
            bucketed_timestamps[-60:]
        )

        if tenant_id not in tenant_map:

            tenant_map[tenant_id] = {
                "tenant_id": int(tenant_id),
                "total_requests": 0,
                "total_failures": 0,
                "total_allowed": 0,
                "total_blocked": 0,
                "total_latency": 0.0,
                "routes": []
            }

        tenant_map[tenant_id]["routes"].append({
            "route_id": int(route_id),
            "total_requests": total_requests,
            "allowed_requests": allowed,
            "blocked_requests": blocked,
            "backend_failures": failures,
            "avg_latency": avg_latency,
            "timestamps": bucketed_timestamps
        })

        tenant_map[tenant_id]["total_requests"] += (
            total_requests
        )

        tenant_map[tenant_id]["total_failures"] += (
            failures
        )

        tenant_map[tenant_id]["total_allowed"] += (
            allowed
        )

        tenant_map[tenant_id]["total_blocked"] += (
            blocked
        )

        tenant_map[tenant_id]["total_latency"] += (
            total_latency
        )

    for tenant in tenant_map.values():

        if tenant["total_allowed"] > 0:

            tenant["avg_latency"] = (
                tenant["total_latency"] /
                tenant["total_allowed"]
            )

        else:

            tenant["avg_latency"] = 0

        del tenant["total_latency"]

        result["tenants"].append(
            tenant
        )

    return result