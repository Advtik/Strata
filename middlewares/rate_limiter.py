import time
from fastapi import Request, Response
import redis.exceptions

from core.redis_client import r
from typing import List,cast

from core.repository import get_rate_limit_by_api_key


RATE_LIMIT_SCRIPT = """
    local key=KEYS[1]
        
    local now = tonumber(ARGV[1])
    local refill_rate=tonumber(ARGV[2])
    local capacity= tonumber(ARGV[3])

    --get existing state
    local data = redis.call("HMGET",key,"tokens","last_refill")

    local tokens=tonumber(data[1])
    local last_refill=tonumber(data[2])

    --initializing if empty
    if tokens == nil then
        tokens=capacity
        last_refill=now
    end

    --refill
    local elapsed=now-last_refill
    tokens=tokens+(elapsed*refill_rate)

    if tokens>capacity then
        tokens=capacity
    end

    --decision
    local allowed = 0
    if tokens >= 1 then 
        allowed = 1
        tokens=tokens-1
    end

    --update state
    redis.call("HMSET",key,"tokens",tokens,"last_refill",now)
    redis.call("EXPIRE", key, 7200)

    return {allowed,tokens}
"""

# load script once
RATE_LIMIT_SHA = cast(str, r.script_load(RATE_LIMIT_SCRIPT))


async def rate_limiter(request:Request, call_next):
    now = time.time()

    # get api key
    api_key = getattr(request.state, "api_key", None)
    if api_key is None:
        return Response(content="Missing API Key", status_code=401)

    rate_config = await get_rate_limit_by_api_key(api_key)

    if rate_config is None:
        # fallback (fail open)
         return await call_next(request)

    refill_rate = rate_config["refill_rate"]
    capacity = rate_config["capacity"]

    # safer key (still your design, just safe fallback)
    path = request.url.path or "default"
    key = f"rate:{api_key}:{path}"

    global RATE_LIMIT_SHA

    try:
        result = cast(List, r.evalsha(RATE_LIMIT_SHA, 1, key, now, refill_rate, capacity))

    except redis.exceptions.NoScriptError:
        # Redis lost script → reload and update global
        RATE_LIMIT_SHA = cast(str, r.script_load(RATE_LIMIT_SCRIPT))
        result = cast(List, r.evalsha(RATE_LIMIT_SHA, 1, key, now, refill_rate, capacity))
    except Exception:
        # FAIL OPEN (important)
        return await call_next(request)
    

    allowed = int(result[0])
    tokens = float(result[1])

    remaining = max(0, int(tokens))

    # calculate reset time once
    if refill_rate > 0:
        if allowed == 0:
            reset_time = (1 - tokens) / refill_rate
        else:
            reset_time = (capacity - tokens) / refill_rate
    else:
        reset_time = 0

    # BLOCK
    if allowed == 0:
        response = Response(content="Too many requests", status_code=429)
        response.headers["X-RateLimit-Limit"] = str(capacity)
        response.headers["X-RateLimit-Remaining"] = "0"
        response.headers["X-RateLimit-Reset"] = str(int(now + reset_time))
        response.headers["Retry-After"] = str(max(0, int(reset_time)))
        return response

    # ALLOW
    response = await call_next(request)

    response.headers["X-RateLimit-Limit"] = str(capacity)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    response.headers["X-RateLimit-Reset"] = str(int(now + reset_time))
    response.headers["Retry-After"] = str(max(0, int(reset_time)))

    return response