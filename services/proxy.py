import httpx
import random
import time
from fastapi import Request, Response

from core.health import is_backend_healthy
from core.circuit import can_request, record_success, record_failure
from core.cache import cache
from core.metrics import record_metric
from core.backend_metrics import record_backend_success, record_backend_failure
from core.backend_metrics import pick_best_backend, get_backend_score


async def proxy_handler(pref: str, full_path: str, request: Request):
    query_params = request.query_params
    tenant = request.state.tenant

    print("PROXY HIT")
    print(pref)
    print("tenant ", tenant)

    start_time = time.time()

    routes = cache["routes"].get(tenant["id"])
    if routes is None:
        return Response(content="No routes for tenant", status_code=404)

    route = routes.get(pref)
    if route is None:
        return Response(content="Route not found", status_code=404)

    # NEW (extract route_id)
    route_id = route["route_id"]

    backend_list = route["backends"]
    if not backend_list:
        return Response(content="No backend available", status_code=502)

    healthy_backends = []
    unhealthy_backends = []

    # 🔍 classify backends
    for backend in backend_list:
        backend_url = backend["url"]

        # 🚫 circuit breaker check
        if not can_request(route_id, backend["id"]):
            print("Circuit OPEN, skipping:", backend_url)
            continue

        # UPDATED (use IDs)
        if is_backend_healthy(route_id, backend["id"]):
            healthy_backends.append(backend)
        else:
            unhealthy_backends.append(backend)

    print("Healthy:", healthy_backends)
    print("Unhealthy:", unhealthy_backends)

    #  fallback logic
    if not healthy_backends and not unhealthy_backends:
        print("All circuits open → fallback to all backends")
        backends = backend_list.copy()
    else:
        backends = healthy_backends + unhealthy_backends

    # clean headers
    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("content-length", None)
    headers.pop("connection", None)

    body = await request.body()

    # reuse client
    async with httpx.AsyncClient(timeout=5.0) as client:

        # smart retry loop
        tried = set()

        while len(tried) < len(backends):
            # UPDATED (use route_id)
            backend = pick_best_backend(route_id, backends)
            if not backend:
                return Response("No backends detected", status_code=402)

            # UPDATED (use IDs)
            score = get_backend_score(route_id, backend["id"])
            print(f"Picked backend: {backend['url']} | Score: {score}")

            if backend is None:
                break

            backend_url = backend["url"]

            # avoid retrying same backend
            if backend_url in tried:
                remaining = [b for b in backends if b["url"] not in tried]
                if not remaining:
                    break
                backend = remaining[0]
                backend_url = backend["url"]

            tried.add(backend_url)

            target_url = f"{backend['url'].rstrip('/')}/{full_path}"

            print("Trying backend:", backend_url)

            try:
                backend_start = time.time()

                response = await client.request(
                    method=request.method,
                    url=target_url,
                    headers=headers,
                    params=query_params,
                    content=body
                )

                backend_latency = time.time() - backend_start

                # treat 5xx as failure
                if response.status_code >= 500:
                    record_failure(route_id,backend["id"])

                    record_backend_failure(
                        route_id=route_id,
                        backend_id=backend["id"],
                        latency=backend_latency
                    )

                    print("Server error from backend:", backend_url)
                    continue

                #success
                record_success(route_id, backend["id"])

                # using ID
                record_backend_success(
                    route_id=route_id,
                    backend_id=backend["id"],
                    latency=backend_latency
                )

                excluded = {
                    "content-length",
                    "transfer-encoding",
                    "connection",
                    "content-encoding"
                }

                resp_headers = {}
                for k, v in response.headers.items():
                    if k.lower() not in excluded:
                        resp_headers[k] = v

                print("Upstream status:", response.status_code)

                total_latency = time.time() - start_time

                record_metric(
                    tenant_id=tenant["id"],
                    route_id=route_id,   #use ID
                    latency=total_latency,
                    status="allowed"
                )

                return Response(
                    content=response.content,
                    status_code=response.status_code,
                    headers=resp_headers
                )

            except httpx.RequestError:
                record_failure(route_id, backend["id"])

                # UPDATED (use IDs)
                record_backend_failure(
                    route_id=route_id,
                    backend_id=backend["id"]
                )

                print("Failed backend:", backend_url)
                continue

    #all backends failed
    total_latency = time.time() - start_time

    record_metric(
        tenant_id=tenant["id"],
        route_id=route_id,
        latency=total_latency,
        status="failure"
    )

    return Response(content="All upstreams failed", status_code=502)