import time 

metrics = {}

RETENTION_SECONDS = 600  # 10 mins

def record_metric(tenant_id, route_name, latency, status):
    current_time=int(time.time())

    cutoff = current_time - RETENTION_SECONDS

    # initialize tenant
    if tenant_id not in metrics:
        metrics[tenant_id] = {}

    # initialize route
    if route_name not in metrics[tenant_id]:
        metrics[tenant_id][route_name] = {
            "total_requests": 0,
            "allowed_requests": 0,
            "blocked_requests": 0,
            "backend_failures": 0,
            "total_latency": 0.0,
            "timestamps": []
        }
        

    route_metrics = metrics[tenant_id][route_name]
    # update metrics
    route_metrics["total_requests"] += 1

    #timestamps metrics
    if "timestamps" not in route_metrics:
        route_metrics["timestamps"] = []

    timestamps = route_metrics["timestamps"]

    if timestamps and timestamps[-1]["time"] == current_time:
        timestamps[-1]["count"] += 1
    else:
        timestamps.append({
            "time": current_time,
            "count": 1
        })
    
    route_metrics["timestamps"] = [
        t for t in timestamps if t["time"] >= cutoff
    ]


    if status == "blocked":
        route_metrics["blocked_requests"] += 1
        return

    if status == "failure":
        route_metrics["backend_failures"] += 1

    if status == "allowed":
        route_metrics["allowed_requests"] += 1


    route_metrics["total_latency"] += latency




def get_metrics():
    result = {"tenants": []}

    for tenant_id, routes in metrics.items():
        tenant_total_requests = 0
        tenant_total_failures = 0
        tenant_total_latency = 0.0
        tenant_total_allowed=0
        tenant_total_blocked=0

        route_list = []

        for route_name, data in routes.items():
            total_requests = data["total_requests"]
            allowed = data["allowed_requests"]
            blocked = data["blocked_requests"]
            failures = data["backend_failures"]
            total_latency = data["total_latency"]

            avg_latency = total_latency / allowed if allowed > 0 else 0

            minute_buckets = {}

            for entry in data.get("timestamps", []):
                minute = entry["time"] - (entry["time"] % 60)

                if minute not in minute_buckets:
                    minute_buckets[minute] = 0

                minute_buckets[minute] += entry["count"]

            # convert to list
            bucketed_timestamps = [
                {"time": t, "count": c}
                for t, c in sorted(minute_buckets.items())
            ]

            bucketed_timestamps= bucketed_timestamps[-60:]

            route_list.append({
                "name": route_name,
                "total_requests": total_requests,
                "allowed_requests": allowed,
                "blocked_requests": blocked,
                "backend_failures": failures,
                "avg_latency": avg_latency,
                "timestamps": bucketed_timestamps
            })

            tenant_total_requests += total_requests
            tenant_total_failures += failures
            tenant_total_latency += total_latency
            tenant_total_allowed += allowed
            tenant_total_blocked += blocked

        tenant_avg_latency = (
            tenant_total_latency / tenant_total_allowed
            if tenant_total_allowed > 0 else 0
        )

        result["tenants"].append({
            "tenant_id": tenant_id,
            "total_requests": tenant_total_requests,
            "total_failures": tenant_total_failures,
            "total_allowed": tenant_total_allowed,
            "total_blocked": tenant_total_blocked,
            "avg_latency": tenant_avg_latency,
            "routes": route_list
        })

    return result