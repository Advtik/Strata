# Strata Proxy Core — Progress So Far

## 1. What has been built

You have built the **core transport engine** of Strata: a generic reverse-proxy endpoint that receives an HTTP request, sanitizes it, forwards it to an upstream backend, receives the upstream response, sanitizes that response, and returns it back to the client.

Current mental model:

Client → Strata → Upstream API → Strata → Client

This means Strata is already behaving like a real reverse proxy at the transport layer.

---

## 2. Current request flow

### Step 1: Receive incoming request

FastAPI captures:

- full path after `/proxy/`
- HTTP method
- query parameters
- headers
- body

Example:

`/proxy/get?name=test`

FastAPI captures:

- full_path = `get`
- method = `GET`
- query params = `name=test`

---

### Step 2: Build target URL

A base URL is currently hardcoded:

`https://postman-echo.com`

Then target URL becomes:

`https://postman-echo.com/get`

Important idea:

Today hardcoded base URL = tomorrow DB lookup result.

---

### Step 3: Sanitize request headers

Incoming browser/client headers cannot be blindly forwarded.

Headers removed:

- host
- content-length
- connection

Why:

These belong to the local transport connection, not upstream transport.

This is called **request sanitization**.

---

### Step 4: Forward request upstream

HTTPX AsyncClient sends request dynamically:

- method=request.method
- url=target_url
- params=query_params
- content=request body
- headers=filtered headers

Important concept:

`client.request(...)` makes proxy generic for all methods.

So now:

- GET remains GET
- POST remains POST
- PUT remains PUT
- PATCH remains PATCH
- DELETE remains DELETE

---

### Step 5: Receive upstream response

Upstream returns:

- response body
- response headers
- status code

---

### Step 6: Sanitize response headers

Certain response headers are removed:

- content-length
- transfer-encoding
- connection
- content-encoding

Why:

These may conflict when FastAPI rebuilds final response.

This is called **response sanitization**.

---

### Step 7: Return final response

FastAPI returns:

- upstream content
- upstream status code
- filtered response headers

This preserves upstream truth.

---

## 3. Why this is important

At this stage you have already implemented:

- path forwarding
- query forwarding
- method forwarding
- body forwarding
- request header filtering
- response header filtering
- status code preservation

This is already the true heart of a reverse proxy.

---

## 4. Important reverse proxy concepts learned

## Request is not just URL

A request contains:

- method
- path
- query params
- headers
- body

A proxy must preserve all meaningful parts.

---

## Headers are policy, not blind copy

Some headers must be forwarded.

Some must be removed.

Examples removed:

- host
- connection
- content-length

Reason:

They belong to hop-level transport.

This introduces the concept:

### Hop-by-hop headers vs End-to-end headers

---

## Response also needs filtering

Not only request.

Response headers also carry transport semantics.

---

## Method carries intent

Examples:

- GET = fetch
- POST = create
- PUT = replace
- PATCH = partial modify
- DELETE = remove

Preserving method means preserving semantic meaning.

---

## Query params are separate from path

Example:

`/proxy/get?name=test`

Path = get

Query = name=test

Both must travel separately.

---

## 5. Why hardcoded base URL is temporary

Right now:

`baseURL = "https://postman-echo.com"`

This is temporary.

Later:

base URL will come from route registry / database.

Meaning:

Developer registers backend once.

Strata stores:

- prefix
- base URL

Then runtime requests resolve automatically.

---

## 6. Why route registry is next

Current limitation:

Every request goes to one backend.

Next gateway step:

Different prefixes decide different upstreams.

Example:

- echo → postman-echo
- json → jsonplaceholder

Request:

`/proxy/echo/get`

Flow:

- prefix = echo
- remaining path = get
- base URL lookup
- final upstream build

---

## 7. Current code maturity level

This is no longer basic FastAPI practice.

This is already:

### Generic multi-method proxy core

That means the transport engine of Strata exists.

---

## 8. Architectural truth reached so far

Everything built until now belongs to:

### Transport layer

Not yet:

- auth layer
- rate limiting
- tenant routing
- load balancing
- health checks

Those come after route intelligence.

---

## 9. Strong summary sentence

What exists now:

A clean proxy core that faithfully transports HTTP requests while sanitizing protocol-sensitive headers.

That is the foundation on which Strata will grow.
