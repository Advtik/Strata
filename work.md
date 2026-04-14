# Strata — Complete Build Journal

> *A living document of how Strata was built from zero — every decision, every concept, every iteration, every failure, and every upgrade explained in full. If you're reading this, you're reading the story of how a real API gateway gets built from scratch.*

---

## What Is Strata?

Strata is an API gateway being built from scratch.

Not a tutorial project. Not a clone. A real piece of infrastructure software — the kind that sits in front of every backend service in a production system and makes a decision about every single request that enters the system. Auth, routing, rate limiting, load balancing, observability — all of it lives inside Strata.

The approach: build it layer by layer, understanding *why* each piece exists before writing a single line of code for it. Every phase introduces a new real-world problem. Strata's evolution is the documented solution to those problems, one at a time.

---

## The Mental Model (Keep This in Your Head Always)

```
Client → [ Strata ] → Upstream Service → [ Strata ] → Client
```

Strata lives in the middle. It owns zero business logic. It owns the **control plane** — who can talk to what, how often, and whether the request even reaches the upstream at all.

As Strata grows, more logic happens inside that middle bracket. That bracket *is* the gateway. Right now it looks like this:

```
Client
  → Strata [
      Logging
      → Authentication
        → Rate Limiting
          → Route Authorization
            → Proxy Forward
  ]
  → Upstream
  → Strata [attach headers]
  → Client
```

---

## Phase 1 — The Raw Reverse Proxy

### The Problem Being Solved

The very first question: how does a piece of software receive an HTTP request and forward it somewhere else? This sounds trivial. It is not. Understanding exactly what travels in a request, what needs to be preserved, what needs to be stripped, and how to handle async forwarding correctly is the entire foundation that everything else is built on.

### What Was Built

A transparent reverse proxy. One job: receive an HTTP request, forward it to the right upstream, pass the response back untouched.

The URL structure was designed from the start:

```
/proxy/{prefix}/{full_path}
```

The `prefix` acts as a key into a route registry. A request to `/proxy/echo/get` maps `echo` to its upstream and forwards to `http://postman-echo.com/get`. A request to `/proxy/json/posts/1` maps `json` and forwards to `http://jsonplaceholder.typicode.com/posts/1`.

The route registry was a simple Python dictionary:

```python
routes = {
    "echo": "http://postman-echo.com",
    "json": "http://jsonplaceholder.typicode.com"
}
```

The route handler:

```python
@app.api_route(
    "/proxy/{pref}/{full_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"]
)
async def root(pref: str, full_path: str, request: Request):
    baseURL = routes.get(pref)
    if not baseURL:
        return Response(content="Route not found", status_code=404)

    target_url = f"{baseURL.rstrip('/')}/{full_path}"
    ...
```

### Concept: Generic Multi-Method Forwarding

The `@app.api_route` decorator with a list of methods means one handler serves all HTTP verbs. The method is read from the incoming request and forwarded as-is to the upstream. This is intentional — a proxy should not care what method the client is using. It just passes it on.

```python
async with httpx.AsyncClient(timeout=15.0) as client:
    response = await client.request(
        method=request.method,        # whatever the client sent
        url=target_url,
        headers=headers,
        params=query_params,
        content=await request.body()  # raw body, no parsing
    )
```

### Concept: Why httpx and Not requests

Python's `requests` library is synchronous — when it makes a network call, it blocks the entire thread until the upstream responds. In an async framework like FastAPI, blocking the thread means no other requests can be processed during that wait. With `httpx.AsyncClient`, the call is `await`-ed, which means the event loop is free to handle other requests while waiting for the upstream. This is the difference between handling 10 concurrent requests and handling 1000.

### Concept: Hop-by-Hop Header Stripping

When a proxy forwards a request, it must strip certain headers before sending them upstream. These are called **hop-by-hop headers** — they're instructions for the *current* TCP connection, not for the application at the other end.

**On the outbound request (client → upstream):**

```python
headers = dict(request.headers)
headers.pop("host", None)           # upstream has its own host
headers.pop("content-length", None) # httpx recalculates this
headers.pop("connection", None)     # belongs to TCP negotiation
```

- `host` — every HTTP request includes the hostname the client thinks it's talking to. If you forward `host: strata.myserver.com` to `postman-echo.com`, the upstream gets confused.
- `content-length` — httpx calculates the correct length from the body being sent. If you forward the original value it may be wrong.
- `connection` — TCP-level instruction. Meaningless to the application.

**On the inbound response (upstream → client):**

```python
excluded = {"content-length", "transfer-encoding", "connection", "content-encoding"}
resp_headers = {k: v for k, v in response.headers.items() if k.lower() not in excluded}
```

- `content-encoding` — the upstream may have gzip-encoded its response. `httpx` decodes it automatically. If you forward the `content-encoding: gzip` header, the client will try to decode already-decoded content and get garbage.
- `transfer-encoding` — chunked encoding is a transport-level concern. FastAPI handles its own encoding when it builds the response.
- `content-length` — the length of the original upstream response body may differ from what FastAPI sends after processing.

Not stripping these headers correctly causes silent, hard-to-debug failures on the client side. This is one of the most important details in proxy implementation.

### Concept: The Route Registry Pattern

The `routes` dictionary is not just a configuration detail — it's the first version of what will become Strata's **route registry**. A prefix maps to an upstream base URL. The proxy doesn't know anything about what the upstream does. It just knows where to send the request. This separation of *routing logic* from *business logic* is a core principle of API gateways.

### What Phase 1 Left Unsolved

The proxy worked perfectly — but it was completely open. Any client that knew the URL structure could call any upstream, as many times as they wanted, with no identity attached to the request. There was no way to answer three fundamental questions that every production system must answer:

1. **Who are you?** (Authentication)
2. **Are you allowed to do this?** (Authorization)
3. **Are you doing this too often?** (Rate Limiting)

Phase 1 was a transport layer. Phase 2 adds the control layer on top.

---

## Phase 2 — Building the Control Layer

### The Architecture Shift

Phase 2 turned Strata from a proxy into the beginning of a real API gateway. The approach was to add a middleware stack on top of the existing proxy. Each middleware is an independent layer that handles one concern, in a specific order.

FastAPI middleware registration has a subtle but critical behavior: **middlewares execute in reverse registration order.** The last middleware registered runs first. So Strata registers them in this order in the code:

```python
# Registration order in source code:
@app.middleware("http")
async def rate_limiter(...):    # registered first → runs THIRD

@app.middleware("http")
async def auth_middleware(...): # registered second → runs SECOND

@app.middleware("http")
async def middleman(...):       # registered third → runs FIRST
```

Which produces this execution order on every request:

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

Every middleware uses the `call_next` pattern:

```python
async def some_middleware(request: Request, call_next):
    # before the request goes deeper
    response = await call_next(request)  # hand off to next layer
    # after the response comes back
    return response
```

`call_next` is an async coroutine. When you `await` it, execution suspends here and resumes in the next layer down. When that layer returns a response, execution resumes here. This is how the stack wraps — each layer literally surrounds every layer inside it.

---

### Layer 1 — The Middleman (Observability)

**The problem:** Without logging, debugging is impossible. You have no idea what's happening, how fast it's happening, or where failures occur.

The middleman middleware is registered last (runs outermost) because it needs to time the *entire* request — including auth, rate limiting, and proxying. If it ran inside auth, it would miss the auth processing time.

```python
@app.middleware("http")
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

**Why `time.perf_counter()` and not `time.time()`?**

`time.time()` is wall-clock time — it can jump backward if the system clock is adjusted (NTP sync, daylight saving time, etc.). `time.perf_counter()` is a monotonic counter designed specifically for measuring elapsed time. It is always increasing and has nanosecond resolution. For latency measurement, always use `perf_counter`.

**Why catch and re-raise exceptions?**

If an unhandled exception bubbles up from a deeper layer, the middleware needs to log the 500 and then `raise e` to let FastAPI's own error handling deal with it. If you just let the exception propagate without catching it, the latency never gets logged for 500 cases. The try/except/raise pattern gives you observability without swallowing errors.

**Concept learned: Observability is not optional.**

In a system where requests flow through multiple layers and get proxied to external services, you cannot reason about correctness or performance without logs. The middleman is the foundation everything else is debugged against. Every production incident starts with logs.

---

### Layer 2 — The Tenant System and Authentication

**The problem:** The proxy had no concept of identity. Anyone could call anything. The solution requires building two things simultaneously: a data model for tenants, and middleware that validates identity against that model.

#### The Tenant Data Model

A tenant in Strata represents one API consumer. It has a name, an API key that identifies it, and a list of upstream routes it's allowed to call.

```python
tenants = {
    "key1": {
        "name": "user1",
        "routes": ["echo"]          # can only call the echo upstream
    },
    "key2": {
        "name": "user2",
        "routes": ["json", "echo"]  # can call both upstreams
    }
}
```

The API key is the dictionary key. The value is everything Strata knows about that tenant. This structure was deliberately simple — it stores in memory, requires no database, and can be looked up in O(1). It's the right starting point before introducing persistence.

**Why store allowed routes per tenant?**

In a multi-tenant gateway, different clients have different contracts. A free-tier user might only be allowed to call certain upstreams. A paid user gets access to everything. This is a core multi-tenancy feature, and it's implemented at the data model level so the authorization logic in the route handler stays a simple membership check.

#### The Auth Middleware

```python
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    key_header = request.headers.get("x-api-key")

    if key_header is None:
        return Response(content="Missing API Key", status_code=401)

    tenant = tenants.get(key_header)

    if tenant is None:
        return Response(content="Invalid API Key", status_code=401)

    # Enrich request state for downstream layers
    request.state.tenant = tenant
    request.state.api_key = key_header

    response = await call_next(request)
    return response
```

Two failure cases, both 401:

- **Missing header** — the client didn't send an API key at all.
- **Invalid key** — the client sent a key, but it doesn't exist in the tenant store.

Both return 401 (Unauthorized). The error message text is different so you can distinguish them in logs, but both result in the same HTTP status because from the client's perspective, both mean "you didn't authenticate successfully."

**Concept learned: Request state as a contract between middleware layers.**

`request.state` is a namespace object attached to the Starlette request. It has no schema — you can attach any attribute to it. Auth middleware writes `request.state.tenant` and `request.state.api_key`. Every downstream layer (rate limiter, route handler) reads these without re-querying the tenant store.

This is the FastAPI equivalent of **context propagation** in distributed systems — instead of passing identity data through function arguments, you put it on a shared context object that any layer can read. The contract is: if auth middleware has run successfully, `request.state.api_key` and `request.state.tenant` will always be populated. Downstream layers can trust this without defensive checks.

**Concept learned: Authentication vs Authorization.**

These are two different questions that get conflated constantly:

- **Authentication** = *Who are you?* Proving identity. The auth middleware does this. It reads the API key and looks up the tenant.
- **Authorization** = *Are you allowed?* Checking permission. The route handler does this. It checks whether the authenticated tenant's route list includes the requested prefix.

They're intentionally separated. Auth runs in middleware (early, before any routing). Authorization runs in the route handler (late, where the specific route being requested is known). You can't do authorization in middleware because middleware doesn't know which route is being requested yet — that path parameter gets parsed later by FastAPI's router.

---

### Layer 3 — Rate Limiting: The Full Story

This is the most technically deep component in Phase 2. Rate limiting has its own intellectual history, and Strata went through that history in full — starting with the naive approach, hitting its failure mode, implementing the improved approach, hitting *its* failure mode, and then landing on Token Bucket. Understanding this progression is as important as understanding the final implementation.

#### First Implementation: Sliding Window Log

The initial rate limiter used a **Sliding Window Log** approach. For each API key, it stored a `deque` (double-ended queue) of timestamps — one timestamp entry per request.

```python
from collections import deque

rate_store = {}  # api_key → deque of timestamps

# On each request:
now = time.time()
window = 60  # 60-second window
limit = 10   # 10 requests per window

if api_key not in rate_store:
    rate_store[api_key] = deque()

log = rate_store[api_key]

# Remove timestamps older than the window
while log and log[0] < now - window:
    log.popleft()

# Check if limit exceeded
if len(log) >= limit:
    return Response(content="Too many requests", status_code=429)

# Allow: record this request
log.append(now)
```

The idea: always look back exactly one window (60 seconds). Any timestamp older than `now - 60` gets discarded from the front of the deque. Count what's left. If it's at or above the limit, deny. Otherwise, allow and record the current timestamp.

**Why this approach was chosen first:**

It fixes the most obvious problem with Fixed Window Counter. Fixed Window resets at a fixed clock boundary — every minute exactly at :00. An attacker can send 10 requests at 10:00:59 and 10 more at 10:01:01, getting 20 requests through in 2 seconds because both sets fall within different windows. Sliding Window doesn't have a reset boundary. The window slides with time. There's no exploitable edge.

**Why this was eventually replaced:**

Two problems accumulated as understanding deepened.

The first is **memory cost**. The deque stores one timestamp per request. A tenant sending 10,000 requests per hour means 10,000 entries in memory for that key. At scale — thousands of tenants at high request rates — the memory usage becomes a real operational problem. The scan to remove expired timestamps also takes O(expired entries) time per request.

The second is **no burst tolerance**. If a tenant is allowed 100 requests per minute but sends 100 requests in the first second, they hit their limit for the remaining 59 seconds — even if they send absolutely nothing for those 59 seconds. Legitimate usage patterns are often bursty: a user triggers a batch export that makes 50 API calls in a second, then nothing for two minutes. Punishing bursts identically to sustained abuse is wrong for most API products.

These two gaps — memory cost and zero burst tolerance — are exactly what motivated the investigation into Token Bucket.

#### The Rate Limiting Algorithm Investigation

Before writing the new implementation, the full landscape of rate limiting algorithms was studied. Here's the complete progression:

**Fixed Window Counter** — Count requests per fixed time window (e.g., per minute). Reset counter at the boundary. Trivial to implement, O(1) memory. Fatal flaw: the boundary attack. Send requests straddling two window boundaries to get 2× the limit in a short burst.

**Sliding Window Log** — Store every request timestamp. On each request, discard old entries and count the rest. Mathematically perfect, no boundary to exploit. Fatal flaw: O(requests) memory. Unusable at scale.

**Sliding Window Counter** — Store just two numbers: previous window count and current window count. Estimate the sliding count using a weighted average:
```
estimated = prev_count × (window - elapsed_in_current) / window + curr_count
```
O(1) memory, good accuracy (error < 1/window_size). Still no burst tolerance. A good algorithm for simple cases, but not the final answer.

**Leaky Bucket** — Process requests at a perfectly constant rate, like water dripping through a hole. Excess requests queue up (if queue isn't full) or get dropped. Great for smooth output — used in network switches, video streaming, anything that needs perfectly uniform downstream throughput. Fatal flaw for APIs: it *punishes legitimate bursts*. A user who waits 30 seconds and then needs 10 quick requests gets throttled identically to an abuser. Idle time does not save up capacity.

**Token Bucket** — The winner. Tokens accumulate over time at a steady rate. Each request consumes one token. No tokens = request denied. The bucket has a maximum capacity, which caps how many tokens can accumulate. This is the key insight Leaky Bucket lacks: **idle time saves up burst capacity**.

The decision to switch to Token Bucket was not arbitrary. It was driven by two specific gaps in Sliding Window Log: memory cost and burst tolerance. Token Bucket fixes both simultaneously.

#### The Token Bucket Implementation

**The mental model:**

```
Tokens refill at rate R (tokens/second), capped at capacity C
          ↓ ↓ ↓ ↓ ↓ ↓ ↓ (continuous)
     ┌─────────────────────────┐
     │  🪙 🪙 🪙 🪙 🪙 🪙    │  ← capacity C (max tokens)
     └─────────────────────────┘
               ↓
     Request arrives → consume 1 token → ALLOW ✓
     Request arrives → 0 tokens → DENY  ✗ (429)
```

**The two independent controls:**

- `refill_rate` — tokens added per second. This is the *sustained throughput limit*. Over a long enough window, no tenant can exceed this rate.
- `capacity` — maximum tokens the bucket can hold. This is the *burst allowance*. A tenant idle for 5 seconds with capacity=10 accumulates 5 tokens (or all 10 if they were already partially full) and can fire that many requests immediately.

This maps cleanly to real product requirements: "Users can burst up to 10 requests at once, but sustained throughput is capped at 1 request per second."

**Per-tenant configuration:**

```python
rate_limit_config = {
    "key1": {
        "refill_rate": 1,   # 1 token per second sustained
        "capacity": 10      # burst up to 10 requests
    },
    "key2": {
        "refill_rate": 1,
        "capacity": 5       # smaller burst allowance
    }
}
```

Different tenants have different policies. key1 can burst more than key2 even though their sustained rates are identical. These are two separate knobs.

**Default policy for unrecognized keys:**

```python
rate_config = rate_limit_config.get(api_key)
if rate_config is None:
    rate_config = {"refill_rate": 5, "capacity": 30}
    rate_limit_config[api_key] = rate_config
```

If a key passes auth but has no rate config, Strata creates a generous default instead of crashing. This prevents failures if a tenant gets added to the tenant store but someone forgets the rate config. The default is written back to `rate_limit_config` so it persists for the lifetime of the process.

**The token state store:**

```python
rate_store = {}  # api_key → {"tokens": float, "last_refill": float}
```

Just two numbers per tenant. Compare to the deque-per-tenant of Sliding Window Log. This is O(1) memory per tenant regardless of request volume. A tenant sending a million requests per day uses the same memory as one sending one request per day.

**New tenants start with a full bucket:**

```python
rate = {"tokens": capacity, "last_refill": now}
```

A brand-new tenant gets `capacity` tokens from the start. This is intentional and standard — you don't want to punish a legitimate new user by making them wait for their bucket to fill before they can make their first requests.

**The complete rate limiter middleware:**

```python
@app.middleware("http")
async def rate_limiter(request: Request, call_next):
    now = time.time()

    api_key = request.state.api_key  # written by auth middleware
    if api_key is None:
        return Response(content="Missing API Key", status_code=401)

    # Get config (or create default)
    rate_config = rate_limit_config.get(api_key)
    if rate_config is None:
        rate_config = {"refill_rate": 5, "capacity": 30}
        rate_limit_config[api_key] = rate_config

    refill_rate = rate_config["refill_rate"]
    capacity = rate_config["capacity"]

    # Get or initialize token state
    rate = rate_store.get(api_key)
    if rate is None:
        rate = {"tokens": capacity, "last_refill": now}
        rate_store[api_key] = rate

    tokens = rate["tokens"]
    last_refill = rate["last_refill"]

    # ---- REFILL LOGIC ----
    elapsed = now - last_refill
    tokens += elapsed * refill_rate   # add tokens proportional to elapsed time
    tokens = min(capacity, tokens)    # cap at bucket maximum
    last_refill = now                 # update refill timestamp

    # ---- DENY CASE ----
    if tokens < 1:
        reset_time = (1 - tokens) / refill_rate if refill_rate > 0 else 0

        response = Response(content="Too many requests", status_code=429)
        response.headers["X-RateLimit-Limit"] = str(capacity)
        response.headers["X-RateLimit-Remaining"] = "0"
        response.headers["X-RateLimit-Reset"] = str(int(now + reset_time))

        rate_store[api_key]["tokens"] = tokens
        rate_store[api_key]["last_refill"] = last_refill
        return response

    # ---- ALLOW CASE ----
    tokens -= 1  # consume one token
    rate_store[api_key]["tokens"] = tokens
    rate_store[api_key]["last_refill"] = last_refill

    response = await call_next(request)

    # Attach rate limit headers to the response
    reset_time = (capacity - tokens) / refill_rate if refill_rate > 0 else 0
    response.headers["X-RateLimit-Limit"] = str(capacity)
    response.headers["X-RateLimit-Remaining"] = str(int(tokens))
    response.headers["X-RateLimit-Reset"] = str(int(now + reset_time))

    return response
```

**Breaking down the refill math:**

```python
elapsed = now - last_refill      # seconds since last request
tokens += elapsed * refill_rate  # tokens earned during idle time
tokens = min(capacity, tokens)   # can't exceed the bucket
```

This is **continuous-time refill**. Tokens aren't added on a schedule (e.g., "+1 token every second"). They're calculated based on real elapsed time at the moment of each request. If `refill_rate = 1` and 2.7 seconds have passed, you get exactly 2.7 tokens added (before capping). This is more accurate and fair than scheduled refills because it doesn't matter exactly when a request arrives relative to a tick boundary.

**Breaking down the X-RateLimit headers:**

```
X-RateLimit-Limit:     10           → bucket capacity (the ceiling)
X-RateLimit-Remaining: 7            → tokens left after this request
X-RateLimit-Reset:     1718043200   → Unix timestamp when bucket will be full
```

These follow the de-facto standard used by GitHub, Stripe, Twitch, and most major public APIs. The `Reset` header lets smart clients implement graceful backoff — instead of hammering the API until they get a 429, they check this header and pause until they know more tokens will be available.

**Reset time calculation — two different formulas:**

On the deny path (tokens < 1):
```python
reset_time = (1 - tokens) / refill_rate
```
This is: "how many seconds until there's 1 token — the earliest a request can possibly succeed."

On the allow path:
```python
reset_time = (capacity - tokens) / refill_rate
```
This is: "how many seconds until the bucket is completely full again."

The deny path gives the client the minimum wait. The allow path gives the client the full refill time. Both are useful for different client strategies.

#### Algorithm Comparison That Drove the Decision

| Algorithm | Memory | Burst tolerance | Boundary exploit | Complexity |
|---|---|---|---|---|
| Fixed Window Counter | O(1) | No | Yes — fatal | Trivial |
| Sliding Window Log | O(requests) | No | No | Low |
| Sliding Window Counter | O(1) | No | Partial | Medium |
| Leaky Bucket | O(1) | No — punishes bursts | No | Low |
| **Token Bucket** | **O(1)** | **Yes** | **No** | **Low** |

Token Bucket is the only algorithm in this list that simultaneously achieves constant memory, burst tolerance, and no boundary exploit. This is not a coincidence — it's why AWS, Stripe, GitHub, and most major API infrastructure standardized on it.

---

### Layer 4 — Route Authorization (Inside the Route Handler)

Authentication (layer 2) established *who* the tenant is. Rate limiting (layer 3) established that they haven't exceeded their quota. The route handler asks the final question: *are they allowed to call this specific route?*

```python
@app.api_route(
    "/proxy/{pref}/{full_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"]
)
async def root(pref: str, full_path: str, request: Request):
    tenant = request.state.tenant  # written by auth middleware

    # Check 1: Does this route prefix exist in Strata's registry?
    baseURL = routes.get(pref)
    if not baseURL:
        return Response(content="Route not found", status_code=404)

    # Check 2: Is this tenant allowed to use this specific route?
    if pref not in tenant["routes"]:
        return Response(content="route not allowed", status_code=403)

    # Both passed — build target URL and forward
    target_url = f"{baseURL.rstrip('/')}/{full_path}"
    ...
```

**Why 404 before 403?**

The order of these checks is a deliberate security decision. If you check tenant permissions first on a non-existent route, you'd return 403 — which implicitly tells the client "this route exists, you just can't access it." That leaks information about what routes exist in Strata's internal registry. Checking 404 first prevents this information leakage: a non-existent route always returns 404 regardless of who's asking.

**Why is authorization in the route handler and not in middleware?**

Authorization requires knowing which route is being requested. Middleware runs before FastAPI's router parses path parameters — at middleware time, `{pref}` hasn't been extracted yet. You'd have to manually re-parse the URL path in middleware, duplicating FastAPI's routing logic. The clean design: auth (identity check, no route knowledge needed) lives in middleware; authorization (route-specific permission check) lives in the handler where the route is already parsed.

**The query params forwarding:**

```python
query_params = request.query_params

async with httpx.AsyncClient(timeout=15.0) as client:
    response = await client.request(
        method=request.method,
        url=target_url,
        headers=headers,
        params=query_params,   # forwarded as-is to upstream
        content=await request.body()
    )
```

Query parameters are passed through without inspection. Strata doesn't care about `?page=2&limit=50` — that's between the client and the upstream. The proxy passes it on transparently.

**The 502 case:**

```python
except httpx.RequestError:
    return Response(content="Upstream unavailable", status_code=502)
```

If `httpx` can't reach the upstream (DNS failure, connection refused, timeout), Strata returns 502 Bad Gateway. This is the correct status: the request reached Strata fine, but Strata couldn't reach the upstream. 502 tells the client "Strata is working, the problem is downstream."

---

### The Complete Request Lifecycle

Here is every step a real request takes through Strata today, with full detail at each point:

```
CLIENT SENDS:
  GET /proxy/echo/get
  Headers: x-api-key: key1
─────────────────────────────────────────────
↓
MIDDLEMAN MIDDLEWARE (enters)
  Records: start_time = perf_counter()
  Calls: await call_next(request)
─────────────────────────────────────────────
  ↓
  AUTH MIDDLEWARE
    Reads header: x-api-key → "key1"
    Looks up: tenants["key1"]
      → found: {name: "user1", routes: ["echo"]}
    Writes: request.state.tenant = {name:..., routes:[...]}
    Writes: request.state.api_key = "key1"
    Calls: await call_next(request)
    ─────────────────────────────────────────
      ↓
      RATE LIMITER MIDDLEWARE
        Reads: request.state.api_key = "key1"
        Gets config: {refill_rate: 1, capacity: 10}
        Gets state: {tokens: 8.2, last_refill: T-1.8s}

        Refill calc:
          elapsed = 1.8s
          new_tokens = 8.2 + (1.8 × 1) = 10.0
          capped at capacity: 10.0

        Tokens >= 1 → ALLOW
          tokens = 10.0 - 1 = 9.0
          saves state: {tokens: 9.0, last_refill: now}

        Calls: await call_next(request)
        ─────────────────────────────────────
          ↓
          ROUTE HANDLER
            Parses: pref="echo", full_path="get"
            Lookup: routes["echo"] → "http://postman-echo.com" ✓
            Authz: "echo" in tenant["routes"] → ["echo"] ✓
            Build URL: http://postman-echo.com/get
            Strip headers: host, content-length, connection
            Forward via httpx → upstream
            ─────────────────────────────────
              ↓
              UPSTREAM: postman-echo.com/get
              ↑ responds: 200 OK + body
            ─────────────────────────────────
            Strip response headers: content-encoding,
              transfer-encoding, content-length, connection
            Returns: Response(content, 200, filtered_headers)
          ↑
        RATE LIMITER MIDDLEWARE (resuming)
          Calculates reset_time = (10-9)/1 = 1s
          Attaches to response:
            X-RateLimit-Limit: 10
            X-RateLimit-Remaining: 9
            X-RateLimit-Reset: <now+1>
          Returns response
        ↑
      AUTH MIDDLEWARE (resuming)
        No action — passes response up
        ↑
MIDDLEMAN MIDDLEWARE (resuming)
  duration = (perf_counter() - start_time) × 1000 = 43ms
  Logs: {method:GET, url:/proxy/echo/get, status:200, latency:43}
  Returns response
↑
CLIENT RECEIVES:
  200 OK
  X-RateLimit-Limit: 10
  X-RateLimit-Remaining: 9
  X-RateLimit-Reset: 1718043201
  Body: {...postman echo response...}
```

**What happens on auth failure (key missing):**

```
CLIENT SENDS: GET /proxy/echo/get (no x-api-key header)

→ MIDDLEMAN (enters, starts timer)
  → AUTH MIDDLEWARE
      Reads header: x-api-key → None
      Returns: Response("Missing API Key", 401)  ← chain stops here
  ← AUTH MIDDLEWARE (returns 401 directly, call_next never called)
← MIDDLEMAN (resumes, logs: status=401, latency=0.1ms)

CLIENT RECEIVES: 401 Missing API Key
```

The rate limiter and route handler never run. The upstream is never touched.

**What happens on rate limit exceeded:**

```
CLIENT SENDS: GET /proxy/echo/get (key1, but tokens=0.3)

→ MIDDLEMAN (enters)
  → AUTH MIDDLEWARE (passes, enriches state)
    → RATE LIMITER
        tokens after refill = 0.3 + elapsed × 1 = 0.8
        0.8 < 1 → DENY
        reset_time = (1 - 0.8) / 1 = 0.2 seconds
        Returns: Response("Too many requests", 429) + headers
    ← (call_next never called)
  ← AUTH MIDDLEWARE
← MIDDLEMAN (logs: status=429)

CLIENT RECEIVES: 429 Too Many Requests
  X-RateLimit-Limit: 10
  X-RateLimit-Remaining: 0
  X-RateLimit-Reset: <now + 0.2s>
```

---

## How Everything Connects

The architecture has no accidental cohesion — every connection is intentional.

**request.state is the data bus.** Auth is the only layer that touches the tenant store. It writes the result onto `request.state`. Every downstream layer reads from this shared context. No layer duplicates the work of a previous layer. This is context propagation — the same pattern used in Go's `context.Context`, OpenTelemetry tracing, and distributed request headers.

**call_next is the control valve.** Each middleware decides: call `call_next` (pass request deeper) or return a Response directly (short-circuit). Short-circuiting is how early rejection works. If any layer returns early, all subsequent layers are skipped entirely. The upstream is never called unless every control check passes.

**The middleware order encodes logical dependencies.** Logging wraps everything because it needs to measure total time. Auth runs before rate limiting because you need an identity before you can apply a per-identity quota. Rate limiting runs before the route handler because you want to reject quota-exceeded requests *before* doing the work of building the upstream request. Authorization runs in the route handler because only there do you know which specific route is being requested.

**The error codes are a coherent contract.** Each failure mode returns a specific status code with specific semantics. Clients that understand these codes can react appropriately — retry with credentials on 401, stop on 403, backoff on 429, surface a service issue on 502. A system that returns 500 for everything is opaque. Strata's error contract is explicit.

---

## Error Response Map

| Status | Where | Cause | What the client should do |
|---|---|---|---|
| `401` | Auth middleware | Missing or invalid API key | Fix credentials, retry |
| `403` | Route handler | Tenant not allowed on this route | Contact admin for access |
| `404` | Route handler | Prefix not in route registry | Check the URL |
| `429` | Rate limiter | Token bucket empty | Wait until X-RateLimit-Reset |
| `502` | Route handler | Upstream unreachable (httpx error) | Surface as upstream outage |

---

## What Phase 2 Added vs Phase 1

| Capability | Phase 1 | Phase 2 |
|---|---|---|
| Forward HTTP requests | ✓ | ✓ |
| Multi-method support | ✓ | ✓ |
| Header stripping (in + out) | ✓ | ✓ |
| Tenant identity model | ✗ | ✓ per-key name + routes |
| API key authentication | ✗ | ✓ middleware |
| Rate limiting | ✗ | ✓ Token Bucket per tenant |
| Configurable per-tenant limits | ✗ | ✓ refill_rate + capacity |
| Per-tenant route authorization | ✗ | ✓ allowlist per key |
| Request logging | ✗ | ✓ method + path + status + latency |
| Standard HTTP error codes | ✗ | ✓ 401, 403, 404, 429, 502 |
| Client-visible rate state | ✗ | ✓ X-RateLimit-* on every response |
| Default policy for unknown keys | ✗ | ✓ auto-created on first request |

---

## Key Engineering Concepts Mastered

### Middleware chain order is an architectural decision

The order isn't a detail — it's the correctness guarantee of the whole system. Logging must wrap everything to measure true end-to-end latency. Auth must precede rate limiting (can't quota by identity without knowing identity). Auth must precede authorization (same reason). Each layer depends on the invariants established by earlier layers. Changing the order would break these invariants.

### Request context propagation

`request.state` is the handoff mechanism. Auth writes tenant identity once. Every layer downstream reads it without re-fetching. This pattern — establish identity early, propagate it via context — is used in Go's `context.Context`, Java's `ThreadLocal`, OpenTelemetry's trace context, and distributed request ID headers. The principle is universal.

### Continuous-time token bucket

The refill calculation uses real elapsed time (`elapsed * refill_rate`), not scheduled ticks. This means the math is always exactly correct regardless of when a request arrives. No rounding errors from batch refills. No edge cases at tick boundaries. The formula is simple and the guarantees are tight.

### Token bucket gives two independent guarantees

`capacity` (burst ceiling) and `refill_rate` (sustained throughput) are independent controls. You can have a large burst with a slow refill (batch job use case), or a small burst with a fast refill (real-time API use case). The two-knob model maps directly to real business requirements in a way that single-parameter algorithms cannot.

### Sliding window log as a stepping stone

The initial sliding window implementation wasn't wasted — it taught the failure modes that motivated Token Bucket. Understanding what algorithm you're replacing and *why* is how you avoid replacing Token Bucket with something worse in the future.

### Hop-by-hop vs end-to-end headers

HTTP headers split into two categories: instructions for the current connection (hop-by-hop: Connection, Transfer-Encoding, Content-Length, Content-Encoding) and instructions for the final destination (end-to-end: Content-Type, Authorization, custom headers). A proxy strips hop-by-hop and forwards end-to-end. Getting this wrong produces silent failures.

### 401 / 403 / 429 are semantically distinct

These are not interchangeable. 401 = unknown identity. 403 = known identity, not permitted. 429 = known identity, permitted, but too frequent. Clients handle each differently. The choice of status code is the API contract with the caller.

### Information leakage in error responses

Returning 403 on a non-existent route reveals the route exists. Checking 404 first prevents this. Error responses are a security surface, not just debugging aids.

---

## Current Limitations (Honest Assessment)

Phase 2 is functional. It is not production-ready. These limitations are documented as the architectural work of Phase 3.

**In-memory rate state.** `rate_store` is a Python dict in process memory. Server restart resets all token counts — every tenant gets a full bucket on restart. Exploitable as a primitive bypass (restart the server), and simply wrong operationally.

**Not distributed.** Two Strata instances have two separate `rate_store` dicts. A tenant can exhaust their tokens on server A, then hit server B for a fresh bucket. Rate limiting is per-process, not per-tenant globally. This is the single most critical gap.

**Potential race condition.** The read-compute-write on `rate_store[api_key]` is not atomic. Under concurrent requests for the same API key, two requests could both read the same token count and both be allowed, effectively passing both through on one token. Python's GIL reduces (but does not eliminate) this in CPython; asyncio's cooperative scheduling further reduces it, but it's still a real gap for high-concurrency deployments.

**Hardcoded configuration.** `tenants`, `routes`, and `rate_limit_config` are Python dicts in source code. Adding a tenant requires editing source and redeploying. This does not scale operationally.

**No persistence.** No database. Restart = clean slate.

**No retry logic.** A transient 503 from upstream becomes a 502 to the client immediately.

**No load balancing.** Each prefix maps to exactly one upstream URL.

**No health checks.** Strata forwards blindly. A dead upstream produces 502 on every request until manually fixed.

---

## What Comes Next

### Phase 3 — Distributed Rate Limiting (Redis)

Replace `rate_store` (in-memory Python dict) with Redis. The Token Bucket algorithm stays identical — only the storage layer changes. With Redis, token state is shared across every Strata instance running behind a load balancer. Rate limiting becomes truly global per tenant.

The atomic operation challenge: reading tokens, calculating refill, and writing back must be one indivisible operation. The solution is a Redis Lua script — Lua scripts execute atomically on the Redis server, making the entire read-compute-write a single operation with no race conditions.

### Phase 4 — Persistent Tenant and Route Configuration

Move `tenants`, `routes`, and `rate_limit_config` to PostgreSQL. Add an admin API for CRUD operations. Adding or removing a tenant becomes an API call, not a code change or redeploy.

### Phase 5 — Load Balancing

Each route entry becomes a list of upstream URLs. Strata distributes requests across them. Strategies: round-robin (simple, stateless), least-connections (routes to the instance with fewest active requests), weighted (custom allocation percentages).

### Phase 6 — Health Checks

A background asyncio task pings each upstream periodically. Failed health checks mark an upstream unavailable. Requests route around it. Recovery re-adds it to rotation. This is the difference between a gateway that fails silently and one that degrades gracefully.

### Phase 7 — Metrics and Observability

The middleman already collects latency and status codes. Phase 7 exposes these as Prometheus-compatible metric endpoints and adds a real-time dashboard. P99 latency, request rate by tenant, error rate, rate limit hit rate, upstream health — all visible.

### Phase 8 — Retry Logic and Circuit Breaking

Transient upstream failures get automatic retries with exponential backoff. A circuit breaker prevents Strata from forwarding to a clearly degraded upstream — instead of piling up retries and increasing latency, it fast-fails until the upstream recovers.

---

## Architecture Level Today

```
Strata (Phase 2):

  Transport Layer
  ├── Generic HTTP forwarding (GET, POST, PUT, PATCH, DELETE)
  ├── Hop-by-hop header stripping (outbound + inbound)
  ├── Async proxying via httpx.AsyncClient
  └── Query parameter passthrough

  Control Layer (Middleware Stack)
  ├── Observability   — method, path, status, latency (ms)
  ├── Authentication  — API key → tenant identity via request.state
  ├── Rate Limiting   — Token Bucket, continuous-time refill, per-tenant config
  └── Authorization   — per-tenant route allowlist, enforced in route handler

  Data Models (in-memory)
  ├── Tenant registry    — api_key → {name, routes[]}
  ├── Route registry     — prefix → upstream base URL
  ├── Rate limit config  — api_key → {refill_rate, capacity}
  └── Rate state store   — api_key → {tokens, last_refill}
```

This is the **API gateway control plane core**. The same category of software as Kong, Traefik, and AWS API Gateway. Not a tutorial project. Infrastructure built with full understanding of every architectural decision.

---

## Full Evolution

```
Phase 1 — Raw Reverse Proxy  [complete]
  Built:    URL-prefix routing, generic method forwarding,
            httpx async client, hop-by-hop header stripping
  Learned:  Proxy mechanics, async I/O, route registry pattern,
            HTTP header semantics
  Gap:      No identity, no limits, no access control — open tunnel

Phase 2 — API Gateway Core  [complete, current]
  Built:    Middleman logging, auth middleware, tenant data model,
            sliding window log rate limiter → replaced with Token Bucket,
            route authorization, X-RateLimit headers
  Learned:  Middleware chain order, request.state propagation,
            rate limiting algorithm evolution and tradeoffs,
            continuous-time token refill, error code semantics,
            information leakage in error responses
  Gap:      In-memory only, not distributed, no persistence,
            no retry, no load balancing, potential race condition

Phase 3 — Distributed Rate Limiting  [next]
  Plan:     Redis backend for rate_store, atomic Lua scripts,
            global per-tenant limits across all Strata instances

Phase 4 — Persistent Configuration  [future]
  Plan:     PostgreSQL for tenants/routes/config, admin CRUD API,
            runtime configuration without redeployment

Phase 5 — Load Balancing  [future]
  Plan:     Multiple upstreams per prefix, round-robin / weighted strategies

Phase 6 — Health Checks  [future]
  Plan:     Background pinger, automatic upstream rotation on failure

Phase 7 — Metrics  [future]
  Plan:     Prometheus endpoints, latency histograms, real-time dashboard

Phase 8 — Reliability  [future]
  Plan:     Retry with exponential backoff, circuit breaking,
            configurable timeout policies
```

Every phase builds directly on the last. The Phase 1 proxy core is still running under everything in Phase 2 — untouched. The Phase 2 Token Bucket implementation will have its storage layer swapped to Redis in Phase 3, but the algorithm, the headers, the middleware contract, and the error codes stay identical. Only the backend changes.
