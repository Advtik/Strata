import httpx
import random
from fastapi import Request, Response

from core.health import health_status
from core.circuit import can_request, record_success, record_failure
from core.repository import get_routes_for_tenant
from core.cache import cache 


async def proxy_handler(pref:str,full_path:str,request:Request):
    query_params=request.query_params
    tenant=request.state.tenant

    print("PROXY HIT")
    print(pref)
    print("tenant ",tenant)

    routes = cache["routes"].get(tenant["id"])
    if(routes is None):
        return Response(content="No routes for tenant", status_code=404)
    
    route=routes.get(pref)
    if route is None:
        return Response(content="Route not found",status_code=404)

    backend_list=route["backends"]
    if not backend_list:
        return Response(content="No backend available", status_code=502)
    
    healthy_backends = []
    unhealthy_backends = []

    route_health = health_status.get(pref,{})

    # 🔍 classify backends
    for backend in backend_list:
        backend_url=backend["url"]
        state = route_health.get(backend_url)

        # 🚫 circuit breaker check
        if not can_request(backend):
            print("Circuit OPEN, skipping:", backend_url)
            continue

        if state is None:
            healthy_backends.append(backend)
        elif state["healthy"]:
            healthy_backends.append(backend)
        else:
            unhealthy_backends.append(backend)

    print("Healthy:", healthy_backends)
    print("Unhealthy:", unhealthy_backends)

    # 🎯 fail-open fallback (VERY IMPORTANT)
    if not healthy_backends and not unhealthy_backends:
        print("All circuits open → fallback to all backends")
        backends = backend_list.copy()
        random.shuffle(backends)
    else:
        # 🎯 priority: healthy first
        random.shuffle(healthy_backends)
        random.shuffle(unhealthy_backends)
        backends = healthy_backends + unhealthy_backends

    # 🧼 clean headers
    headers=dict(request.headers)
    headers.pop("host", None)
    headers.pop("content-length", None)
    headers.pop("connection", None)

    body=await request.body()

    # 🔁 retry loop
    for backend in backends:
        target_url = f"{backend['url'].rstrip('/')}/{full_path}"

        print("Trying backend:", backend["url"])

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.request(
                    method=request.method,
                    url=target_url,
                    headers=headers,
                    params=query_params,
                    content=body
                )

            # 🚨 treat 5xx as failure
            if response.status_code >= 500:
                record_failure(backend)
                print("Server error from backend:", backend["url"])
                continue

            # ✅ success
            record_success(backend)

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

            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=resp_headers
            )

        except httpx.RequestError:
            record_failure(backend)
            print("Failed backend:", backend["url"])
            continue

    return Response(content="All upstreams failed", status_code=502)