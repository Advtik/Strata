from core.redis_client import r
import json


async def get_route_metrics_service(tenant_id: int, route_id: int):

    key = f"metrics:{tenant_id}:{route_id}"
    ts_key = f"metrics_ts:{tenant_id}:{route_id}"
    

    data = r.hgetall(key)

    def to_int(x): return int(x or 0)
    def to_float(x): return float(x or 0)

    total_requests = to_int(data.get("total_requests"))
    allowed = to_int(data.get("allowed_requests"))
    blocked = to_int(data.get("blocked_requests"))
    failures = to_int(data.get("backend_failures"))
    total_latency = to_float(data.get("total_latency"))

    avg_latency = total_latency / allowed if allowed > 0 else 0

    # ----------------------------
    # TIMELINE (reuse your logic)
    # ----------------------------
    raw_ts = r.lrange(ts_key, 0, -1)
    timestamps = [json.loads(t) for t in raw_ts]

    minute_buckets = {}

    for entry in timestamps:
        minute = entry["time"] - (entry["time"] % 60)

        if minute not in minute_buckets:
            minute_buckets[minute] = 0

        minute_buckets[minute] += entry["count"]

    timeline = [
        {"time": t, "count": c}
        for t, c in sorted(minute_buckets.items())
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


async def get_backends_metrics_service(route_id: int):

    keys = list(r.scan_iter(f"backend:{route_id}:*"))

    result = []

    for key in keys:
        key_str = key_str = key if isinstance(key, str) else key.decode()
        _, r_id, backend_id = key_str.split(":")

        data = r.hgetall(key)

        result.append({
            "backend_id": int(backend_id),
            "requests": int(data.get("requests", 0)),
            "successes": int(data.get("successes", 0)),
            "failures": int(data.get("failures", 0)),
            "recent_requests": float(data.get("recent_requests", 0.0)),
            "avg_latency": float(data.get("avg_latency", 0))
        })

    return {
        "route_id": route_id,
        "backends": result
    }