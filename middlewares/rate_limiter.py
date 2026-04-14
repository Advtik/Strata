import time
from fastapi import Request, Response

from core.config import rate_limit_config
from core.state import rate_store


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