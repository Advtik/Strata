import time
import json
from core.redis_client import r

RETENTION_SECONDS = 600  # 10 mins


def _metrics_key(tenant_id, route_id):
    return f"metrics:{tenant_id}:{route_id}"


def _timestamps_key(tenant_id, route_id):
    return f"metrics_ts:{tenant_id}:{route_id}"


def record_metric(tenant_id, route_id, latency, status):
    current_time = int(time.time())
    cutoff = current_time - RETENTION_SECONDS

    key = _metrics_key(tenant_id, route_id)
    ts_key = _timestamps_key(tenant_id, route_id)

    # initialize route (same logic)
    if not r.exists(key):
        r.hset(key, mapping={
            "total_requests": 0,
            "allowed_requests": 0,
            "blocked_requests": 0,
            "backend_failures": 0,
            "total_latency": 0.0
        })

    # update metrics
    r.hincrby(key, "total_requests", 1)

    
    # timestamps logic 
    last = r.lindex(ts_key, -1)
    if last:
        last = json.loads(last)

    if last and last["time"] == current_time:
        last["count"] += 1
        r.lset(ts_key, -1, json.dumps(last))
    else:
        r.rpush(ts_key, json.dumps({
            "time": current_time,
            "count": 1
        }))

    # filtering 
    timestamps = r.lrange(ts_key, 0, -1)

    new_list = []
    for t in timestamps:
        t = json.loads(t)
        if t["time"] >= cutoff:
            new_list.append(t)

    r.delete(ts_key)
    for t in new_list:
        r.rpush(ts_key, json.dumps(t))

    # status logic 
    if status == "blocked":
        r.hincrby(key, "blocked_requests", 1)
        return

    if status == "failure":
        r.hincrby(key, "backend_failures", 1)

    if status == "allowed":
        r.hincrby(key, "allowed_requests", 1)

    r.hincrbyfloat(key, "total_latency", latency)


def get_metrics():
    result = {"tenants": []}

    keys = r.keys("metrics:*")

    tenant_map = {}

    for key in keys:
        key_str = key.decode() if isinstance(key, bytes) else key

        # metrics:tenant_id:route_id
        _, tenant_id, route_id = key_str.split(":", 2)

        data = r.hgetall(key)

        def to_int(x): return int(x or 0)
        def to_float(x): return float(x or 0)

        total_requests = to_int(data.get("total_requests"))
        allowed = to_int(data.get("allowed_requests"))
        blocked = to_int(data.get("blocked_requests"))
        failures = to_int(data.get("backend_failures"))
        total_latency = to_float(data.get("total_latency"))

        avg_latency = total_latency / allowed if allowed > 0 else 0

        # timestamps (same logic)
        ts_key = _timestamps_key(tenant_id, route_id)
        raw_ts = r.lrange(ts_key, 0, -1)

        timestamps = [json.loads(t) for t in raw_ts]

        minute_buckets = {}

        for entry in timestamps:
            minute = entry["time"] - (entry["time"] % 60)

            if minute not in minute_buckets:
                minute_buckets[minute] = 0

            minute_buckets[minute] += entry["count"]

        bucketed_timestamps = [
            {"time": t, "count": c}
            for t, c in sorted(minute_buckets.items())
        ]

        bucketed_timestamps = bucketed_timestamps[-60:]

        # tenant aggregation (same logic)
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

        tenant_map[tenant_id]["total_requests"] += total_requests
        tenant_map[tenant_id]["total_failures"] += failures
        tenant_map[tenant_id]["total_allowed"] += allowed
        tenant_map[tenant_id]["total_blocked"] += blocked
        tenant_map[tenant_id]["total_latency"] += total_latency

    for tenant in tenant_map.values():
        if tenant["total_allowed"] > 0:
            tenant["avg_latency"] = tenant["total_latency"] / tenant["total_allowed"]
        else:
            tenant["avg_latency"] = 0

        del tenant["total_latency"]

        result["tenants"].append(tenant)

    return result