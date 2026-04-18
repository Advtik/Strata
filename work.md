# Strata — Complete Build Journal

> *A living document of how Strata was built from zero — every decision, every concept, every iteration, every failure, and every upgrade explained in full. If you're reading this, you're reading the story of how a real API gateway gets built from scratch.*

---

## What Is Strata?

Strata is an API gateway being built from scratch. Not a tutorial project. Not a clone. A real piece of infrastructure software — the kind that sits in front of every backend service in a production system and makes a decision about every single request that enters the system. Auth, routing, rate limiting, load balancing, observability — all of it lives inside Strata.

The approach: build it layer by layer, understanding *why* each piece exists before writing a single line of code for it. Every phase introduces a new real-world problem. Strata's evolution is the documented solution to those problems, one at a time.

---

## The Core Mental Model

Keep this in your head at all times:

```
Client  →  [ Strata ]  →  Upstream Service  →  [ Strata ]  →  Client
```

Strata lives in the middle. It owns zero business logic. It owns the **control plane** — who can talk to what, how often, and whether the request even reaches the upstream at all.

As of today, the full pipeline inside that middle bracket looks like this:

```
Client
  → Strata [
      Logging (outermost)
      → Authentication
        → Rate Limiting (Redis token bucket)
          → Route Authorization
            → Load Balancer (random shuffle + failover)
              → Upstream
  ]
  → Client
```

---

## Current Architecture Snapshot

Here is the complete file structure that exists right now:

```
strata/
├── core/
│   ├── config.py          ← Route registry, tenant store, rate config
│   ├── redis_client.py    ← Shared Redis connection
│   └── state.py           ← (Legacy in-memory store, no longer used for rate limiting)
├── middlewares/
│   ├── auth.py            ← API key authentication
│   ├── logging.py         ← Request/response timing and logging
│   └── rate_limiter.py    ← Redis-backed token bucket (Lua script)
├── services/
│   └── proxy.py           ← Multi-backend routing with failover
└── main.py                ← FastAPI app, middleware registration
```

### core/config.py — The Central Registry

This file is the single source of truth for Strata's configuration. Three dictionaries live here.

The `routes` dictionary maps a short name (a "prefix") to a list of backend URLs. Notice that each route now has a **list** of backends, not just one. This is what enables load balancing and failover:

```python
routes = {
    "echo": {
        "backends": [
            "http://postman-echo.com",
            "https://httpbin.org"
        ]
    },
    "json": {
        "backends": [
            "http://jsonplaceholder.typicode.com"
        ]
    }
}
```

The `tenants` dictionary maps an API key string to a tenant object. The tenant object stores the human-readable name and the list of route prefixes that tenant is allowed to access:

```python
tenants = {
    "key1": { "name": "user1",  "routes": ["echo"] },
    "key2": { "name": "user2",  "routes": ["json", "echo"] }
}
```

The `rate_limit_config` dictionary maps an API key to its token bucket parameters. These two numbers are the complete definition of a tenant's rate limit policy:

```python
rate_limit_config = {
    "key1": { "refill_rate": 1,   "capacity": 10 },
    "key2": { "refill_rate": 0.2, "capacity": 5  }
}
```

> **Why a list?** In Phase 1 and 2, each route pointed to a single backend URL string. Changing to a list was the foundational change that enabled everything in Phase 4 — multiple backends per route means Strata can distribute, retry, and fail over across them.

### core/redis_client.py — The Shared Connection

A single Redis client shared across the entire application:

```python
import redis

r = redis.Redis(
    host="localhost",
    port=6379,
    decode_responses=True
)
```

The `decode_responses=True` setting tells the Redis client to automatically decode byte strings (what Redis stores internally) into Python strings. Without it, every value you read back from Redis would be a bytes object like `b'9.5'` instead of the string `'9.5'`. This matters because the rate limiter does arithmetic with these values.

This file is imported wherever Redis is needed. Having one shared connection is correct — creating a new connection per request is extremely expensive.

---

## Phase 1 — The Raw Reverse Proxy

> **Goal:** Understand the absolute basics. Receive an HTTP request. Forward it somewhere else. Return the response. That's it.

### The Problem Being Solved

The very first question: how does software receive an HTTP request and forward it somewhere else? This sounds trivial — it is not. Understanding exactly what travels in a request, what needs to be preserved, what needs to be stripped, and how to handle async forwarding correctly is the entire foundation that everything else is built on.

### What Was Built

A transparent reverse proxy. One job: receive an HTTP request, forward it to the right upstream, pass the response back untouched.

The URL structure was designed from the start:

```
/proxy/{prefix}/{full_path}
```

The `prefix` acts as a key into a route registry. A request to `/proxy/echo/get` maps `echo` to its upstream and forwards to `http://postman-echo.com/get`. A request to `/proxy/json/posts/1` maps `json` and forwards to `http://jsonplaceholder.typicode.com/posts/1`.

### Why httpx and Not requests?

Python's `requests` library is synchronous — when it makes a network call, it blocks the entire thread until the upstream responds. In an async framework like FastAPI, blocking the thread means no other requests can be processed during that wait.

With `httpx.AsyncClient`, the call is `await`-ed, which means the event loop is free to handle other requests while waiting for the upstream. This is the difference between handling 10 concurrent requests and handling 1000.

### Concept: Hop-by-Hop Header Stripping

When a proxy forwards a request, it must strip certain headers before sending them upstream. These are called **hop-by-hop headers** — they are instructions for the *current* TCP connection, not for the application at the other end.

**On the outbound request (client → upstream):**

```python
headers = dict(request.headers)
headers.pop("host", None)           # upstream has its own host
headers.pop("content-length", None) # httpx recalculates this
headers.pop("connection", None)     # TCP-level, meaningless to the app
```

- `host` — every HTTP request includes the hostname the client thinks it's talking to. If you forward `host: strata.myserver.com` to `postman-echo.com`, the upstream gets confused.
- `content-length` — httpx calculates the correct length from the body being sent. The original value may be wrong.
- `connection` — TCP-level instruction. Meaningless to the application.

**On the inbound response (upstream → client):**

```python
excluded = {"content-length", "transfer-encoding", "connection", "content-encoding"}
resp_headers = {k: v for k, v in response.headers.items() if k.lower() not in excluded}
```

- `content-encoding` — the upstream may have gzip-encoded its response. `httpx` decodes it automatically. If you forward the `content-encoding: gzip` header, the client will try to decode already-decoded content and get garbage.
- `transfer-encoding` — chunked encoding is a transport-level concern. FastAPI handles its own encoding.
- `content-length` — the length of the original response may differ from what FastAPI sends after processing.

Not stripping these headers correctly produces silent, hard-to-debug failures on the client side.

### What Phase 1 Left Unsolved

The proxy worked perfectly — but it was completely open. Any client that knew the URL structure could call any upstream, as many times as they wanted, with no identity attached to the request. There was no way to answer three fundamental questions:

- **Who are you?** (Authentication)
- **Are you allowed to do this?** (Authorization)
- **Are you doing this too often?** (Rate Limiting)

---

## Phase 2 — The Control Layer (Middleware Stack)

> **Goal:** Turn the open proxy into a real API gateway by adding identity, authorization, and rate limiting as independent, composable layers.

### The Architecture Shift

Phase 2 added a middleware stack on top of the existing proxy. Each middleware is an independent layer that handles one concern, in a specific order.

FastAPI middleware registration has a critical behavior: **middlewares execute in reverse registration order.** The last middleware registered runs first. So the registration order in code:

```python
app.middleware("http")(rate_limiter)    # registered first → runs THIRD
app.middleware("http")(auth_middleware) # registered second → runs SECOND
app.middleware("http")(middleman)       # registered third → runs FIRST
```

...produces this execution order on every request:

```
Incoming Request
  → middleman (logging — outermost wrapper)
    → auth_middleware (identity check)
      → rate_limiter (quota check)
        → route_handler (proxy + authorization)
      ← rate_limiter (attach rate limit headers)
    ← auth_middleware (pass through)
  ← middleman (log result + latency)
Outgoing Response
```

> **Key insight:** The middleware order encodes logical dependencies. Logging wraps everything to measure true end-to-end latency. Auth runs before rate limiting because you need an identity before you can apply a per-identity quota. Rate limiting runs before routing so quota-exceeded requests never touch the upstream.

### The call_next Pattern

Every middleware uses the same pattern:

```python
async def some_middleware(request: Request, call_next):
    # code here runs BEFORE the request goes deeper
    response = await call_next(request)  # hand off to next layer
    # code here runs AFTER the response comes back
    return response
```

When you `await call_next`, execution suspends here and resumes in the next layer down. When that layer returns, execution resumes here. This is how the stack wraps — each layer literally surrounds every layer inside it.

If any layer returns a `Response` directly without calling `call_next`, the entire chain below it is skipped. This is how early rejection works — the upstream is never called unless every check passes.

### Layer 1: The Middleman (Observability)

The middleman middleware is registered last (runs outermost) because it needs to time the *entire* request — including auth, rate limiting, and proxying.

```python
async def middleman(request: Request, call_next):
    start_time = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as e:
        duration = time.perf_counter() - start_time
        print(request.method, request.url.path, 500, duration)
        raise e

    duration = (time.perf_counter() - start_time) * 1000  # ms
    print({
        "method": request.method,
        "url_path": request.url.path,
        "status_code": response.status_code,
        "latency": duration
    })
    return response
```

> **Why `perf_counter` and not `time.time()`?** `time.time()` is wall-clock time and can jump backward if the system clock is adjusted (NTP sync, daylight saving time). `time.perf_counter()` is a monotonic counter that only ever increases, designed specifically for measuring elapsed time with nanosecond resolution. For latency measurement, always use `perf_counter`.

The try/except/raise pattern catches exceptions to log the 500 case, then re-raises so FastAPI's own error handling can deal with them. Without it, failed requests would have no latency log.

### Layer 2: Authentication and the Tenant System

The tenant data model is the foundation of Strata's multi-tenancy. A tenant represents one API consumer — it has a name, an API key, and an allowlist of routes it can access.

The auth middleware reads the `x-api-key` header, looks up the tenant, and if valid writes the result onto `request.state`:

```python
async def auth_middleware(request: Request, call_next):
    key_header = request.headers.get("x-api-key")

    if key_header is None:
        return Response(content="Missing API Key", status_code=401)

    tenant = tenants.get(key_header)

    if tenant is None:
        return Response(content="Invalid API Key", status_code=401)

    request.state.tenant = tenant
    request.state.api_key = key_header

    response = await call_next(request)
    return response
```

Two failure cases, both 401:
- **Missing header** — the client didn't send an API key at all.
- **Invalid key** — the client sent a key, but it doesn't exist in the tenant store.

Both return 401 because from the client's perspective, both mean "you didn't authenticate successfully."

> **Authentication vs Authorization:** These are two different questions. Authentication = *Who are you?* (auth middleware). Authorization = *Are you allowed?* (route handler). They are intentionally separated — auth runs in middleware where the specific route isn't yet known; authorization runs in the handler where the route is already parsed.

`request.state` acts as the data bus between layers. Auth is the only layer that touches the tenant store. It writes the result once, and every downstream layer reads from this shared context without re-fetching. This is the FastAPI equivalent of context propagation — the same pattern used in Go's `context.Context` and OpenTelemetry tracing.

### Layer 3: Rate Limiting — The Full Story

The rate limiter went through a complete evolution before reaching its current form. Understanding this progression is as important as the final implementation.

#### The Algorithm Progression

| Algorithm | Memory cost | Burst tolerance | Boundary exploit | Verdict |
|---|---|---|---|---|
| Fixed Window Counter | O(1) | No | Yes — fatal | Rejected |
| Sliding Window Log | O(requests) | No | No | Replaced (memory cost) |
| Sliding Window Counter | O(1) | No | Partial | Acceptable but limited |
| Leaky Bucket | O(1) | No — punishes bursts | No | Wrong semantics |
| **Token Bucket** | **O(1)** | **Yes** | **No** | **Chosen** |

Token Bucket is the only algorithm that simultaneously achieves constant memory, burst tolerance, and no boundary exploit. This is why AWS, Stripe, GitHub, and most major API infrastructure standardized on it.

#### How Token Bucket Works

Imagine a physical bucket. Tokens accumulate in it over time at a steady rate (`refill_rate`). Each request consumes one token. If the bucket is empty, the request is denied. The bucket has a maximum size (`capacity`) that caps how many tokens can accumulate at once.

```
Two independent controls:
  refill_rate = 1   → tokens per second (sustained throughput limit)
  capacity    = 10  → max tokens (burst allowance)

A tenant idle for 5 seconds with refill_rate=1 accumulates 5 tokens.
They can then fire 5 requests immediately (burst),
but over a long window they can never exceed 1 req/sec (sustained).
```

The refill math uses continuous-time calculation, not scheduled ticks:

```python
elapsed = now - last_refill       # real seconds since last request
tokens += elapsed * refill_rate   # tokens earned proportionally
tokens = min(capacity, tokens)    # cap at bucket maximum
```

If `refill_rate=1` and 2.7 seconds have passed, you get exactly 2.7 tokens added. This is always correct regardless of when a request arrives relative to any tick boundary.

#### The Rate Limit Headers

Strata attaches standard rate limit headers to every response, following the de-facto standard used by GitHub, Stripe, and Twitch:

```
X-RateLimit-Limit: 10         → bucket capacity (the ceiling)
X-RateLimit-Remaining: 7      → tokens left after this request
X-RateLimit-Reset: 1718043200 → Unix timestamp when bucket will be full
Retry-After: 3                → seconds to wait (on 429 responses only)
```

These let smart clients implement graceful backoff — instead of hammering the API until they get a 429, they check these headers and pause until they know more tokens will be available.

> **Phase 2 limitation:** The token state was stored in an in-memory Python dict (`rate_store`). This meant two things: (1) a server restart reset all token counts, and (2) with multiple Strata instances, each had a separate store — a tenant could exhaust their tokens on one instance and get a fresh bucket on another. This was the primary gap that Phase 3 solved.

---

## Phase 3 — Distributed Rate Limiting with Redis

> **Goal:** Move rate limit state out of process memory and into Redis, making limits global across all Strata instances and surviving server restarts.

### The Problem With In-Memory State

The Phase 2 rate limiter worked perfectly on a single server. But real deployments run multiple instances of Strata behind a load balancer. Each instance had its own Python dict in memory:

```
Strata instance 1: tenant key1 has 0 tokens remaining → BLOCK
Strata instance 2: tenant key1 has 10 tokens remaining → ALLOW

Result: rate limiting was per-instance, not per-tenant globally.
A determined client could bypass limits by simply hitting different instances.
```

The fix is a shared store that all Strata instances read from and write to. Redis is the standard choice — it is fast (sub-millisecond reads/writes), supports atomic operations, and is built for exactly this kind of shared ephemeral state.

### The Race Condition Problem

Moving state to Redis introduces a new problem. The token bucket operation has three steps: read the current token count, calculate the new count, write the new count back:

```python
tokens = redis.get("rate:key1")    # step 1: read
tokens = tokens + elapsed * rate   # step 2: calculate
redis.set("rate:key1", tokens)     # step 3: write
```

If two requests from the same tenant arrive simultaneously on two different Strata instances, both could execute step 1 at the same time and read the same value. Both would calculate and write, and one write would overwrite the other. Both requests would be allowed even if only one token remained. This is a **race condition**.

The solution is to make all three steps an **atomic operation** — a single indivisible unit that nothing else can interrupt. Redis provides exactly this through Lua scripts.

### Why a Lua Script?

Redis executes Lua scripts atomically. When Redis starts running a Lua script, no other command from any other client can interrupt it until the script finishes. The entire read-calculate-write sequence happens as one operation from Redis's perspective.

This is not just a nice property — it is the fundamental correctness guarantee of the distributed rate limiter. Without it, concurrent requests would corrupt each other's token counts.

### The Lua Script — Line by Line

```lua
local key          = KEYS[1]          -- e.g. "rate:key1:/proxy/echo/get"
local now          = tonumber(ARGV[1]) -- current Unix timestamp
local refill_rate  = tonumber(ARGV[2]) -- tokens per second
local capacity     = tonumber(ARGV[3]) -- max tokens

-- Read existing state from a Redis hash (two fields in one call)
local data       = redis.call("HMGET", key, "tokens", "last_refill")
local tokens     = tonumber(data[1])
local last_refill = tonumber(data[2])

-- Initialize if this key has never been seen before
if tokens == nil then
    tokens = capacity   -- new tenants start with a full bucket
    last_refill = now
end

-- Refill: calculate tokens earned since last request
local elapsed = now - last_refill
tokens = tokens + (elapsed * refill_rate)
if tokens > capacity then tokens = capacity end

-- Decision
local allowed = 0
if tokens >= 1 then
    allowed = 1
    tokens = tokens - 1
end

-- Write updated state back (atomically, same script)
redis.call("HMSET", key, "tokens", tokens, "last_refill", now)
redis.call("EXPIRE", key, 7200)  -- auto-clean keys inactive for 2 hours

return {allowed, tokens}
```

The script takes the key as `KEYS[1]` and the parameters as `ARGV` arguments. It uses `HMGET` to read both fields (`tokens` and `last_refill`) in one Redis command, performs all the token bucket math in Lua, and uses `HMSET` to write both fields back in one command. The entire thing is one atomic operation.

### Script Loading and the SHA Pattern

Sending the full Lua script text on every request would waste bandwidth. Redis provides a better approach: load the script once with `SCRIPT LOAD`, which returns a SHA hash. On subsequent calls, use `EVALSHA` with the hash to execute the already-loaded script:

```python
# At startup: load script, store the SHA
RATE_LIMIT_SHA = r.script_load(RATE_LIMIT_SCRIPT)

# On each request: execute by SHA (much faster)
result = r.evalsha(RATE_LIMIT_SHA, 1, key, now, refill_rate, capacity)
#                              ^    ^  ^^^
#                              |    |  arguments passed as ARGV
#                              |    number of keys (KEYS array)
#                              SHA hash of the script
```

There is one edge case: Redis can lose scripts if it restarts with its scripting cache cleared. The rate limiter handles this with a `NoScriptError` catch that reloads and retries:

```python
try:
    result = r.evalsha(RATE_LIMIT_SHA, 1, key, now, refill_rate, capacity)
except redis.exceptions.NoScriptError:
    # Redis lost the script cache — reload and retry
    RATE_LIMIT_SHA = r.script_load(RATE_LIMIT_SCRIPT)
    result = r.evalsha(RATE_LIMIT_SHA, 1, key, now, refill_rate, capacity)
except Exception:
    # Redis itself is down — fail open (let the request through)
    return await call_next(request)
```

> **Fail open:** If Redis is completely unavailable, the rate limiter catches the exception and calls `call_next` — it lets the request through rather than blocking it. This is called "fail open" and is the correct design for a rate limiter. The alternative, "fail closed" (blocking all requests when Redis is down), would take down your entire API whenever Redis has a hiccup. Rate limiting is a safety feature, not a gatekeeper.

### The Rate Limit Key Design

The Redis key for each rate limit entry is constructed as:

```python
key = f"rate:{api_key}:{path}"

# Example: "rate:key1:/proxy/echo/get"
```

Including the path in the key means rate limits are **per-tenant-per-route**. If `key1` is limited to 10 requests per second on `/proxy/echo/get`, that limit is independent from their quota on `/proxy/json/posts`.

### What Changed vs Phase 2

| Aspect | Phase 2 (in-memory) | Phase 3 (Redis) |
|---|---|---|
| Storage | Python dict in process memory | Redis hash per tenant+route |
| Multi-instance | Each instance independent | All instances share one store |
| Restart behavior | Token counts reset to full | State persists across restarts |
| Race condition | Possible under concurrency | Eliminated by Lua atomicity |
| Failure mode | Never fails | Fail-open if Redis is down |
| Algorithm | Token bucket (continuous) | Token bucket (identical logic) |

> **Key insight:** The rate limiting algorithm itself did not change at all. The token bucket math, the refill logic, the headers — all identical. Only the storage layer changed from a Python dict to Redis. This is a clean separation of concerns: the algorithm is independent of where the state lives.

---

## Phase 4 — Multi-Backend Routing with Failover

> **Goal:** Each route can now point to multiple backend servers. Strata distributes requests across them and automatically retries on a different backend if one fails.

### The Config Change That Made Everything Possible

In Phases 1–3, each route pointed to a single backend URL string. The change to a list was small in code but large in impact:

```python
# Phase 1-3: single backend
"echo": "http://postman-echo.com"

# Phase 4: list of backends
"echo": {
    "backends": [
        "http://postman-echo.com",
        "https://httpbin.org"
    ]
}
```

This single structural change in `config.py` unlocked load balancing and failover — the proxy just needed to be updated to use the list.

### The Proxy Handler — Full Walkthrough

```python
async def proxy_handler(pref: str, full_path: str, request: Request):
    query_params = request.query_params
    tenant = request.state.tenant

    # Authorization: is this tenant allowed on this route?
    if pref not in tenant["routes"]:
        return Response(content="route not allowed", status_code=403)

    # Does this route exist in Strata's registry?
    route = routes.get(pref)
    if route is None:
        return Response(content="Route not found", status_code=404)

    # Get the backend list
    backend_list = route["backends"]
    if not backend_list:
        return Response(content="No backend available", status_code=502)

    # Shuffle for random load distribution
    backends = backend_list.copy()   # never mutate config
    random.shuffle(backends)

    # Strip hop-by-hop headers
    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("content-length", None)
    headers.pop("connection", None)
    body = await request.body()

    # Try each backend in order; continue on network failure
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
            # Strip hop-by-hop response headers
            excluded = {"content-length", "transfer-encoding",
                        "connection", "content-encoding"}
            resp_headers = {k: v for k, v in response.headers.items()
                            if k.lower() not in excluded}
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=resp_headers
            )
        except httpx.RequestError:
            continue   # network-level failure → try next backend

    return Response(content="All upstreams failed", status_code=502)
```

### The Random Shuffle Strategy

Instead of always trying backends in the same order, the proxy shuffles the list before iterating. This means each request independently picks a random ordering of backends to try.

Over many requests, this produces an even distribution across all healthy backends — the same statistical effect as round robin, but without needing any shared counter or state. Each Strata instance can make this decision independently without coordinating with other instances.

```python
backends = backend_list.copy()   # IMPORTANT: copy first, never mutate config
random.shuffle(backends)          # randomize in place

# With backends = [A, B, C], each request gets a random order:
# Request 1: [B, A, C] → tries B first
# Request 2: [A, C, B] → tries A first
# Request 3: [C, B, A] → tries C first
# Over many requests, A, B, C each get ~1/3 of traffic
```

> **Why copy first?** `backend_list` is a reference to the list inside the `routes` config dict. If you shuffled it directly, you would permanently reorder the backends in config — every future request would see the shuffled order, not the original. Always copy before mutating data you don't own.

### The Failover Loop

The `for` loop over backends is the failover mechanism. On a network-level failure (connection refused, DNS failure, timeout), `httpx` raises an `httpx.RequestError`. The `except` clause catches it and calls `continue`, advancing to the next backend.

```python
for backend in backends:
    try:
        # ... attempt the request ...
        return Response(...)   # success → return immediately
    except httpx.RequestError:
        continue               # failure → try next backend

# If we exit the loop without returning, all backends failed
return Response(content="All upstreams failed", status_code=502)
```

This means Strata automatically routes around dead backends — if `postman-echo.com` is down, it tries `httpbin.org` instead. The client sees a successful response and has no idea a failure occurred. This is **transparent failover**.

> **What counts as a failure?** Only `httpx.RequestError` — which covers network-level failures: connection refused, DNS failure, timeout, SSL errors. It does NOT catch HTTP error status codes like 500 or 503. A backend returning 500 is a valid HTTP response that Strata forwards to the client as-is. Circuit breakers (a future phase) will add the ability to handle application-level errors.

### The 404 Before 403 Decision

The authorization checks happen in a specific order inside the proxy handler:

```python
# Check 1: Does this route exist in Strata's registry?
route = routes.get(pref)
if route is None:
    return Response(content="Route not found", status_code=404)

# Check 2: Is this tenant allowed on this route?
if pref not in tenant["routes"]:
    return Response(content="route not allowed", status_code=403)
```

The order matters. If you check permissions first on a non-existent route, you would return 403 — which implicitly tells the client "this route exists, you just cannot access it." That leaks information about Strata's internal route registry. Checking 404 first prevents this: a non-existent route always returns 404 regardless of who is asking.

---

## The Complete Request Lifecycle

Here is every step a real request takes through Strata today. This is `GET /proxy/echo/get` with `x-api-key: key1`, and both backends available.

```
CLIENT SENDS:
  GET /proxy/echo/get
  Headers: x-api-key: key1
─────────────────────────────────────────────────────────────
↓
MIDDLEMAN (enters)
  Records: start_time = perf_counter()
  ↓
  AUTH MIDDLEWARE
    Reads header: x-api-key → "key1"
    Looks up: tenants["key1"]
      → found: {name: "user1", routes: ["echo"]}
    Writes: request.state.tenant = {...}
    Writes: request.state.api_key = "key1"
    ↓
    RATE LIMITER
      Key: "rate:key1:/proxy/echo/get"
      Runs Lua script atomically on Redis:
        HMGET key → {tokens: 8.2, last_refill: T-1.8s}
        elapsed = 1.8s → new_tokens = 8.2 + 1.8 = 10.0 (capped)
        10.0 >= 1 → ALLOW, tokens = 9.0
        HMSET key tokens=9.0 last_refill=now
        EXPIRE key 7200
        returns {1, 9.0}
      ↓
      PROXY HANDLER
        pref="echo", full_path="get"
        Route check: routes["echo"] exists ✓
        Authz check: "echo" in ["echo"] ✓
        backends = ["http://postman-echo.com", "https://httpbin.org"]
        shuffle → ["https://httpbin.org", "http://postman-echo.com"]
        Try httpbin.org/get → 200 OK
        Strip response headers
        return Response(content, 200, filtered_headers)
      ↑
    RATE LIMITER (resuming)
      Attaches to response:
        X-RateLimit-Limit: 10
        X-RateLimit-Remaining: 9
        X-RateLimit-Reset: <now + 1s>
        Retry-After: 1
    ↑
  AUTH MIDDLEWARE (resuming) → passes through
  ↑
MIDDLEMAN (resuming)
  duration = 47ms
  Logs: {method:GET, url:/proxy/echo/get, status:200, latency:47ms}
  ↑
CLIENT RECEIVES: 200 OK + rate limit headers + response body
```

### Error Response Map

| Status | Layer | Cause | Client action |
|---|---|---|---|
| `401` | Auth | Missing or invalid API key | Fix credentials |
| `403` | Proxy handler | Tenant not allowed on this route | Contact admin |
| `404` | Proxy handler | Prefix not in route registry | Check the URL |
| `429` | Rate limiter | Token bucket empty | Wait until `X-RateLimit-Reset` |
| `502` | Proxy handler | All backends failed (network error) | Surface as upstream outage |

---

## How Everything Connects

### request.state is the data bus

Auth is the only layer that touches the tenant store. It writes the result onto `request.state.tenant` and `request.state.api_key`. Every downstream layer reads from this shared context without re-fetching. No layer duplicates the work of a previous layer. The contract: if auth middleware ran successfully, `request.state.api_key` and `request.state.tenant` are always populated. Downstream layers can trust this invariant.

### call_next is the control valve

Each middleware decides: call `call_next` (pass request deeper) or return a `Response` directly (short-circuit). If any layer returns early, all subsequent layers are skipped entirely. The upstream is never called unless every control check passes. This is how auth failure prevents the rate limiter from even running, and how a rate limit block prevents the proxy from touching the backend.

### The error codes form a coherent contract

Each failure mode returns a specific status code with specific semantics. Clients that understand these codes can react intelligently — retry with new credentials on 401, stop on 403, back off on 429, surface an outage on 502. A system that returns 500 for everything is opaque. Strata's error contract is explicit and meaningful.

---

## Key Engineering Concepts Mastered

### Middleware order is an architectural decision, not a detail

The order encodes logical dependencies. Logging wraps everything to measure true end-to-end latency. Auth must precede rate limiting because you need an identity before you can apply a per-identity quota. Each layer depends on the invariants established by earlier layers. Changing the order breaks correctness, not just style.

### Atomic operations and the distributed correctness problem

Moving state to a shared store (Redis) introduced a race condition that in-memory state never had. The read-modify-write sequence must be atomic. Redis Lua scripts provide this guarantee. This is a general pattern: whenever you have a read-modify-write on shared mutable state, you need to make the whole operation atomic.

### Fail open vs fail closed

When Redis is down, the rate limiter fails open (lets requests through). This is a deliberate safety design: the risk of an occasionally bypassed rate limit is far less severe than taking down your entire API whenever your rate limit store has an outage. Different systems make different choices here — a security-critical access control system might fail closed instead.

### Stateless load distribution

The random shuffle strategy distributes load across backends without any shared state. No counter to coordinate, no consensus needed between Strata instances. Over many requests, the distribution converges to uniform by the law of large numbers. This is the correct approach for load balancing when you want to scale Strata instances horizontally without coordination overhead.

### Never mutate configuration data

The `backend_list.copy()` before shuffling is a small detail with a large consequence. Configuration data is shared state read by every request. Mutating it in one request handler would corrupt every subsequent request. Always copy data before mutating it if the original is shared.

### Information leakage in error responses

Returning 403 on a non-existent route reveals the route exists. Checking 404 first prevents this. Error responses are a security surface, not just debugging aids. Every status code you return is information you are giving to the caller — choose deliberately.

### Continuous-time token bucket

The refill calculation uses real elapsed time (`elapsed * refill_rate`), not scheduled ticks. This means the math is always exactly correct regardless of when a request arrives. No rounding errors from batch refills. No edge cases at tick boundaries.

### Token bucket gives two independent guarantees

`capacity` (burst ceiling) and `refill_rate` (sustained throughput) are independent controls. You can have a large burst with a slow refill (batch job use case), or a small burst with a fast refill (real-time API use case). The two-knob model maps directly to real business requirements in a way that single-parameter algorithms cannot.

---

## Current State — Honest Assessment

### What Works

- Multi-tenant API key authentication
- Per-tenant, per-route Redis token bucket rate limiting (globally consistent)
- Atomic rate limiting via Lua script (no race conditions)
- Graceful Redis failure handling (fail-open)
- Multi-backend routing with random load distribution
- Automatic failover to next backend on network-level failure
- Hop-by-hop header stripping (request and response)
- Request logging with millisecond latency
- Standard rate limit headers on every response
- Per-tenant route authorization

### What Is Still Missing

- **Hardcoded configuration:** `tenants`, `routes`, and `rate_limit_config` are Python dicts in source code. Adding a tenant requires editing source and redeploying.
- **Circuit breakers:** a backend returning 500 repeatedly still receives traffic. There is no mechanism to automatically eject a degraded backend.
- **Active health checks:** Strata only discovers a backend is down when a real request fails. There is no background prober.
- **Retry on application-level errors:** currently only network failures (`httpx.RequestError`) trigger failover. HTTP 503 from a backend is forwarded to the client, not retried.
- **Weighted load balancing:** all backends in a route are treated as equal. There is no way to send more traffic to a more powerful backend.
- **Observability:** logs go to stdout. No metrics endpoint, no Prometheus integration, no latency histograms.
- **Persistence:** no database. Restart = clean tenant/route config (rate limit state survives in Redis).

---

## Full Evolution and What Comes Next

```
Phase 1 — Raw Reverse Proxy  [complete]
  Built:    URL-prefix routing, generic method forwarding,
            httpx async client, hop-by-hop header stripping
  Learned:  Proxy mechanics, async I/O, route registry pattern,
            HTTP header semantics
  Gap:      No identity, no limits, no access control

Phase 2 — API Gateway Core  [complete]
  Built:    Middleman logging, auth middleware, tenant data model,
            token bucket rate limiter (in-memory), route authorization,
            X-RateLimit headers
  Learned:  Middleware chain order, request.state propagation,
            rate limiting algorithm evolution, continuous-time token refill
  Gap:      In-memory only, not distributed, race conditions possible

Phase 3 — Distributed Rate Limiting  [complete]
  Built:    Redis backend for token state, atomic Lua script,
            SHA-based script caching, NoScriptError recovery,
            fail-open on Redis failure
  Learned:  Distributed state problems, atomic read-modify-write,
            Redis Lua scripting, fail-open vs fail-closed design
  Gap:      Single backend per route

Phase 4 — Multi-Backend Routing  [complete, current]
  Built:    Backend list per route, random shuffle load distribution,
            transparent failover on httpx.RequestError
  Learned:  Stateless load balancing, config immutability,
            information leakage in error codes
  Gap:      No health checks, no circuit breakers, no weighted routing

Phase 5 — Health Checks  [next]
  Plan:     Background asyncio task probing each backend periodically,
            automatic exclusion of unhealthy backends from rotation,
            recovery detection and re-inclusion

Phase 6 — Circuit Breakers  [future]
  Plan:     Per-backend state machine (Closed → Open → Half-Open),
            trip on error rate threshold, fast-fail on open circuit,
            probe on timeout, auto-recover on success

Phase 7 — Persistent Configuration  [future]
  Plan:     PostgreSQL for tenants/routes/config, admin CRUD API,
            runtime configuration without code changes or redeployment

Phase 8 — Metrics and Observability  [future]
  Plan:     Prometheus-compatible metrics endpoint, latency histograms,
            request rate by tenant, error rate, rate limit hit rate

Phase 9 — Retry Logic and Weighted Routing  [future]
  Plan:     Retry on 503/504 with exponential backoff and jitter,
            per-backend weights, smooth weighted round robin
```

---

*Strata — built with full understanding of every decision.*