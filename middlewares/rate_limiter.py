import time
from fastapi import Request, Response
import redis.exceptions

from core.redis_client import r
from typing import List, cast

from core.cache import cache
from core.metrics import record_metric
from fastapi.responses import JSONResponse


RATE_LIMIT_SCRIPT = """
    local key=KEYS[1]
        
    local now = tonumber(ARGV[1])
    local refill_rate=tonumber(ARGV[2])
    local capacity= tonumber(ARGV[3])

    local data = redis.call("HMGET",key,"tokens","last_refill")

    local tokens=tonumber(data[1])
    local last_refill=tonumber(data[2])

    if tokens == nil then
        tokens=capacity
        last_refill=now
    end

    local elapsed=now-last_refill
    tokens=tokens+(elapsed*refill_rate)

    if tokens>capacity then
        tokens=capacity
    end

    local allowed = 0
    if tokens >= 1 then 
        allowed = 1
        tokens=tokens-1
    end

    redis.call("HMSET",key,"tokens",tokens,"last_refill",now)
    redis.call("EXPIRE", key, 7200)

    return {allowed,tokens}
"""

RATE_LIMIT_SHA = cast(str, r.script_load(RATE_LIMIT_SCRIPT))


async def rate_limiter(request: Request, call_next):

    #for github oauth
    if request.url.path.startswith("/auth")  or request.url.path.startswith("/api") or request.url.path.startswith("/metrics"):
        return await call_next(request)
    
    now = time.time()

    path_parts = request.url.path.split("/")
    pref = path_parts[2] if len(path_parts) > 2 else "unknown"

    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        return Response(content="No tenant", status_code=401)

    api_key = getattr(request.state, "api_key", None)
    if api_key is None:
        return Response(content="Missing API Key", status_code=401)

    #api key id
    api_key_id = getattr(request.state, "api_key_id", None)
    if api_key_id is None:
        return Response(content="Missing API Key ID", status_code=401)

    rate_config = cache["rate_limits"].get(api_key_id)
    if rate_config is None:
        return Response(content="No Rate limits found", status_code=404)


    # GET route_id FROM CACHE
    routes = cache["routes"].get(tenant["id"])
    if routes is None:
        return Response(content="No routes for tenant", status_code=404)

    route = routes.get(pref)
    if route is None:
        return Response("Route not found", status_code=404)

    route_id = route["route_id"]

    # CONFIG
    global_config = rate_config["global"]

    route_config = rate_config["routes"].get(route_id)
    if route_config is None:
        route_config = global_config  # fallback

    # ✅ UPDATED KEYS (ID-based)
    global_key = f"rate:{api_key_id}"
    route_key = f"rate:{api_key_id}:{route_id}"

    global RATE_LIMIT_SHA

    try:
        # GLOBAL
        global_result = cast(List, r.evalsha(
            RATE_LIMIT_SHA, 1,
            global_key,
            now,
            global_config["refill_rate"],
            global_config["capacity"]
        ))

        global_allowed = int(global_result[0])
        global_tokens = float(global_result[1])

        # ROUTE
        route_result = cast(List, r.evalsha(
            RATE_LIMIT_SHA, 1,
            route_key,
            now,
            route_config["refill_rate"],
            route_config["capacity"]
        ))

        route_allowed = int(route_result[0])
        route_tokens = float(route_result[1])

    except redis.exceptions.NoScriptError:
        RATE_LIMIT_SHA = cast(str, r.script_load(RATE_LIMIT_SCRIPT))
        return await call_next(request)

    except Exception:
        return await call_next(request)

    # RESET TIME CALCULATION
    def get_reset_time(tokens, refill_rate, capacity):
        if refill_rate > 0:
            if tokens < 1:
                return (1 - tokens) / refill_rate
            else:
                return (capacity - tokens) / refill_rate
        return 0

    global_reset = get_reset_time(
        global_tokens,
        global_config["refill_rate"],
        global_config["capacity"]
    )

    route_reset = get_reset_time(
        route_tokens,
        route_config["refill_rate"],
        route_config["capacity"]
    )

    # FINAL DECISION
    if global_allowed == 0 or route_allowed == 0:

        record_metric(
            tenant_id=tenant["id"],
            route_id=route_id,   # ✅ use ID
            latency=0,
            status="blocked"
        )

        if global_allowed == 0:
            limiter = "global"
            limit = global_config["capacity"]
            remaining = max(0, int(global_tokens))
            reset_time = global_reset
        else:
            limiter = "route"
            limit = route_config["capacity"]
            remaining = max(0, int(route_tokens))
            reset_time = route_reset

        response = JSONResponse(
            status_code=429,
            content={
                "error": "rate_limit_exceeded",
                "message": f"{limiter} rate limit exceeded",
                "retry_after": int(reset_time)
            }
        )

        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(int(now + reset_time))
        response.headers["Retry-After"] = str(max(0, int(reset_time)))
        response.headers["X-RateLimit-Type"] = limiter

        return response

    # ALLOW
    response = await call_next(request)

    effective_limit = min(global_config["capacity"], route_config["capacity"])
    remaining = min(int(global_tokens), int(route_tokens))
    reset_time = min(global_reset, route_reset)

    response.headers["X-RateLimit-Limit"] = str(effective_limit)
    response.headers["X-RateLimit-Remaining"] = str(max(0, remaining))
    response.headers["X-RateLimit-Reset"] = str(int(now + reset_time))
    response.headers["Retry-After"] = str(max(0, int(reset_time)))

    return response