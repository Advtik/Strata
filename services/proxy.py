import httpx
from fastapi import Request, Response

from core.config import routes


async def proxy_handler(pref:str,full_path:str,request:Request):
    query_params=request.query_params
    tenant=request.state.tenant
    print(request.headers)
    baseURL=routes.get(pref)
    if not baseURL:
        return Response(content="Route not found", status_code=404)
    
    if(pref not in tenant["routes"]):
        return Response(content="route not allowed", status_code=403)
    
    print(baseURL)
    print(pref)
    target_url=f"{baseURL.rstrip('/')}/{full_path}"
    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("content-length", None)
    headers.pop("connection", None)

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response=await client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                params=query_params,
                content=await request.body()

            )
            excluded = {
                "content-length",
                "transfer-encoding",
                "connection",
                "content-encoding"
            }
            resp_headers={}

            for k,v in response.headers.items():
                if k.lower() not in excluded:
                    resp_headers[k] = v
                    
            return Response(content=response.content, status_code=response.status_code, headers=resp_headers)
    except httpx.RequestError:
        return Response(content="Upstream unavailable",status_code=502)

        