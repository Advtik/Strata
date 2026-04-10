import time

from fastapi import FastAPI, Request, Response
import httpx 
app=FastAPI()

routes={
    "echo":"http://postman-echo.com",
    "json":"http://jsonplaceholder.typicode.com"
}

tenants={
    "key1":{
        "name":"user1",
        "routes":["echo"]
    },
    "key2":{
        "name":"user2",
        "routes":["json","echo"]
    }
}


rate_store = {
    "key1":{
        "recent_requests": [],
        "limit": 3,
        "window_size": 60
    },
    "key2":{
        "recent_requests": [],
        "limit": 4,
        "window_size": 30
    }
}

@app.middleware("http")
async def rate_limiter(request:Request, call_next):
    now = time.time()
    
    # get api key safely
    api_key = request.state.api_key
    if(api_key is None):
        return Response(content="Missing API Key", status_code=401)

    # get or initialize rate config
    rate = rate_store.get(api_key)
    if(rate is None):
        rate = {
            "recent_requests": [],
            "limit": 3,
            "window_size": 60
        }
        rate_store[api_key] = rate

    rate_requests = rate["recent_requests"]
    rate_limit = rate["limit"]
    rate_window = rate["window_size"]

    cutoff = now - rate_window

    # remove old timestamps
    while(len(rate_requests) > 0 and rate_requests[0] < cutoff):
        rate_requests.pop(0)

    # check limit
    if(len(rate_requests) >= rate_limit):
        return Response(content="Too many requests", status_code=429)

    # record current request
    rate_requests.append(now)

    # continue request
    response = await call_next(request)
    return response





@app.middleware("http")
async def auth_middleware(request:Request, call_next):
    key_header = request.headers.get("x-api-key")

    if key_header is None:
        return Response(content="Missing API Key", status_code=401)

    tenant = tenants.get(key_header)

    if tenant is None:
        return Response(content="Invalid API Key", status_code=401)
    
    print(tenant["name"])
    request.state.tenant = tenant
    request.state.api_key=key_header
    response = await call_next(request)
    return response 



@app.middleware("http")
async def middleman(request:Request, call_next):
    start_time = time.perf_counter()
    # print((request.headers))
    try:
        response = await call_next(request)
    except Exception as e:
        time_duration = time.perf_counter() - start_time
        print(request.method, request.url.path, 500, time_duration)
        raise e

    time_duration = (time.perf_counter() - start_time)*1000  #in ms
    print({
        "method":request.method, 
        "url_path":request.url.path, 
        "status_code":response.status_code,
        "latency":time_duration
    })
    return response



@app.api_route("/proxy/{pref}/{full_path:path}",methods=["GET","POST","PUT","PATCH","DELETE"])
async def root(pref:str,full_path:str,request:Request):
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

        

