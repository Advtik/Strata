import httpx
import random
from fastapi import Request, Response

from core.config import routes


async def proxy_handler(pref:str,full_path:str,request:Request):
    query_params=request.query_params
    tenant=request.state.tenant
    print(request.headers)
    print("PROXY HIT")
    print(pref)
    print("tenant ",tenant)

    if(pref not in tenant["routes"]):
        return Response(content="route not allowed", status_code=403)
    
    route=routes.get(pref)
    if route is None:
        return Response(content="Route not found",status_code=404)

    backend_list=route["backends"]
    if not backend_list:
        return Response(content="No backend available", status_code=502)
    
    backends=backend_list.copy()
    random.shuffle(backends)

    headers=dict(request.headers)
    headers.pop("host", None)
    headers.pop("content-length", None)
    headers.pop("connection", None)
    body=await request.body()
    for backend in backends:
        target_url = f"{backend.rstrip('/')}/{full_path}"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.request(
                    method=request.method,
                    url=target_url,
                    headers=headers,
                    params=query_params,
                    content=body
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

            print("Trying backend:", backend)
            print("Upstream status:", response.status_code)
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=resp_headers
            )

        except httpx.RequestError:
            continue  # try next backend

    
    return Response(content="All upstreams failed", status_code=502)

        