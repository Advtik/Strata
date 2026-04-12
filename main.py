import time
from collections import deque
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


# ---------------- CONFIG ----------------
rate_limit_config = {
    "key1": {
        "refill_rate": 1,   # tokens per second
        "capacity": 10
    },
    "key2": {
        "refill_rate": 1,
        "capacity": 5
    }
}

# ---------------- STATE ----------------
rate_store = {}

# ---------------- MIDDLEWARE ----------------
@app.middleware("http")
async def rate_limiter(request:Request, call_next):
    now = time.time()

    # get api key
    api_key = request.state.api_key
    if(api_key is None):
        return Response(content="Missing API Key", status_code=401)

    # get config
    rate_config = rate_limit_config.get(api_key)
    if(rate_config is None):
        rate_config = {
            "refill_rate": 5,
            "capacity": 30
        }
        rate_limit_config[api_key] = rate_config

    refill_rate = rate_config["refill_rate"]
    capacity = rate_config["capacity"]

    # get or initialize state
    rate = rate_store.get(api_key)
    if(rate is None):
        rate = {
            "tokens": capacity,          # start full
            "last_refill": now
        }
        rate_store[api_key] = rate

    tokens = rate["tokens"]
    last_refill = rate["last_refill"]

    #REFILL LOGIC
    elapsed = now - last_refill
    tokens += elapsed * refill_rate
    tokens = min(capacity, tokens)

    # update refill time
    last_refill = now

    #BLOCK CASE
    if(tokens < 1):
        remaining = 0

        # time to get 1 token
        reset_time = (1 - tokens) / refill_rate if refill_rate > 0 else 0

        response = Response(content="Too many requests", status_code=429)
        response.headers["X-RateLimit-Limit"] = str(capacity)
        response.headers["X-RateLimit-Remaining"] = str(int(remaining))
        response.headers["X-RateLimit-Reset"] = str(int(now + reset_time))

        # save updated state
        rate_store[api_key]["tokens"] = tokens
        rate_store[api_key]["last_refill"] = last_refill

        return response

    # ---------------- ALLOW CASE ----------------
    tokens -= 1   # consume token

    remaining = tokens

    # time to full refill
    reset_time = (capacity - tokens) / refill_rate if refill_rate > 0 else 0

    # save updated state
    rate_store[api_key]["tokens"] = tokens
    rate_store[api_key]["last_refill"] = last_refill

    # forward request
    response = await call_next(request)

    # attach headers
    response.headers["X-RateLimit-Limit"] = str(capacity)
    response.headers["X-RateLimit-Remaining"] = str(int(remaining))
    response.headers["X-RateLimit-Reset"] = str(int(now + reset_time))

    return response

#auth middleware in place
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

        

