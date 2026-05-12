import asyncio
import time
import httpx

from fastapi import Request, Response

from core.cache import cache

from core.health import (
    is_backend_healthy
)

from core.metrics import (
    record_metric
)

from core.circuit import (
    can_request,
    record_success,
    record_failure
)

from core.backend_metrics import (
    record_backend_success,
    record_backend_failure,
    get_backend_score
)


client = httpx.AsyncClient(

    timeout=httpx.Timeout(
        connect=0.5,
        read=10.0,
        write=10.0,
        pool=10.0
    ),

    limits=httpx.Limits(
        max_connections=1000,
        max_keepalive_connections=200
    ),

    http2=False
)


EXCLUDED_HEADERS = {
    "content-length",
    "transfer-encoding",
    "connection",
    "content-encoding"
}


async def proxy_handler(
    pref: str,
    full_path: str,
    request: Request
):

    start_time = time.perf_counter()

    tenant = request.state.tenant

    routes = cache["routes"].get(
        tenant["id"]
    )

    if routes is None:

        return Response(
            content="No routes for tenant",
            status_code=404
        )

    route = routes.get(pref)

    if route is None:

        return Response(
            content="Route not found",
            status_code=404
        )

    route_id = route["route_id"]

    backend_list = route["backends"]

    if not backend_list:

        return Response(
            content="No backend available",
            status_code=502
        )

    healthy_backends = []
    unhealthy_backends = []

    for backend in backend_list:

        backend_id = backend["id"]

        allowed = await can_request(
            route_id,
            backend_id
        )

        if not allowed:

            continue

        healthy = await is_backend_healthy(
            route_id,
            backend_id
        )

        if healthy:

            healthy_backends.append(
                backend
            )

        else:

            unhealthy_backends.append(
                backend
            )

    if healthy_backends or unhealthy_backends:

        backends = (
            healthy_backends +
            unhealthy_backends
        )

    else:

        backends = backend_list

    backend_scores = []

    for backend in backends:

        score = await get_backend_score(
            route_id,
            backend["id"]
        )

        backend_scores.append(
            (score, backend)
        )

    backend_scores.sort(
        key=lambda x: x[0]
    )

    sorted_backends = [
        b for _, b in backend_scores
    ]

    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in {
            "host",
            "content-length",
            "connection"
        }
    }

    body = None

    if request.method in {
        "POST",
        "PUT",
        "PATCH"
    }:

        body = await request.body()

    query_params = request.query_params

    for backend in sorted_backends:

        backend_id = backend["id"]

        backend_url = backend["url"]

        target_url = (
            f"{backend_url.rstrip('/')}"
            f"/{full_path}"
        )

        backend_start = (
            time.perf_counter()
        )

        try:

            response = await client.request(
                method=request.method,
                url=target_url,
                headers={
                    **headers,
                    "accept-encoding": "identity"
                },
                params=query_params,
                content=body
            )

            backend_latency = (
                time.perf_counter() -
                backend_start
            )

            if response.status_code >= 500:

                asyncio.create_task(
                    record_failure(
                        route_id,
                        backend_id
                    )
                )

                asyncio.create_task(
                    record_backend_failure(
                        route_id=route_id,
                        backend_id=backend_id
                    )
                )

                continue

            asyncio.create_task(
                record_success(
                    route_id,
                    backend_id
                )
            )

            asyncio.create_task(
                record_backend_success(
                    route_id=route_id,
                    backend_id=backend_id,
                    latency=backend_latency
                )
            )

            resp_headers = {
                k: v
                for k, v in response.headers.items()
                if k.lower() not in EXCLUDED_HEADERS
            }

            total_latency = (
                time.perf_counter() -
                start_time
            )

            asyncio.create_task(
                record_metric(
                    tenant_id=tenant["id"],
                    route_id=route_id,
                    latency=total_latency,
                    status="allowed"
                )
            )

            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=resp_headers
            )

        except httpx.RequestError:

            asyncio.create_task(
                record_failure(
                    route_id,
                    backend_id
                )
            )

            asyncio.create_task(
                record_backend_failure(
                    route_id=route_id,
                    backend_id=backend_id
                )
            )

            continue

    total_latency = (
        time.perf_counter() -
        start_time
    )

    asyncio.create_task(
        record_metric(
            tenant_id=tenant["id"],
            route_id=route_id,
            latency=total_latency,
            status="failure"
        )
    )

    return Response(
        content="All upstreams failed",
        status_code=502
    )