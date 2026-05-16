# Strata

A reverse proxy and API gateway for routing, rate limiting, and monitoring backend traffic through a centralized proxy layer.

---

**Website:** [strata.advtik.com](https://strata.advtik.com)  
**Documentation:** [strata.advtik.com/docs](https://strata.advtik.com/docs)  
**Proxy Endpoint:** [strata-proxy.onrender.com](https://strata-proxy.onrender.com)  
**Frontend Repository:** [github.com/Advtik/Strata-frontend](https://github.com/Advtik/Strata-frontend)  
**Backend Repository:** [github.com/Advtik/Strata](https://github.com/Advtik/Strata)

---

## What It Does

Strata sits between your clients and your backend services. It handles authentication, traffic routing, rate limiting, load balancing, circuit breaking, and observability — all through one proxy layer. You configure routes and backends through a dashboard; Strata does the rest.

---

## Core Features

- **API Key Authentication** — every proxied request is authenticated via `x-api-key` before it reaches a backend
- **Token Bucket Rate Limiting** — distributed, Redis-backed rate limiting with both global (per API key) and per-route limits, implemented atomically via a Lua script
- **Multi-Backend Load Balancing** — routes can have multiple backends; traffic is distributed using an adaptive scoring algorithm that weighs latency, recent failure rate, and load
- **Circuit Breaker** — per-backend state machine (Closed → Open → Half-Open) that automatically ejects failing backends and probes for recovery
- **Active Health Checks** — background task continuously probes each backend and marks it healthy or unhealthy; unhealthy backends are deprioritized in routing
- **Request Metrics** — per-route request counts, latency, blocked/allowed/failed breakdown, and a time-series timeline stored in Redis
- **Backend Metrics** — per-backend request counts, success/failure counts, average latency, and recent failure rates
- **Multi-Tenant Projects** — users create isolated projects (tenants); routes, backends, and API keys are scoped per project
- **GitHub OAuth** — authentication is handled via GitHub OAuth with a JWT stored as an HttpOnly cookie

---

## System Overview

Strata runs as two separate FastAPI applications sharing a PostgreSQL database and Redis:

- **Control App** — the management API consumed by the dashboard. Handles auth, project/route/backend CRUD, rate limit configuration, and metrics retrieval.
- **Gateway App** — the actual proxy. Handles all `/proxy/{route}/{path}` requests through a middleware stack and forwards them to registered backends.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI, asyncpg |
| Proxy runtime | httpx (async) |
| Rate limiting state | Redis (Lua scripts, atomic) |
| Metrics & circuit state | Redis |
| Database | PostgreSQL |
| Frontend | React, Vite, Tailwind CSS v4 |
| Charts | Recharts |
| Auth | GitHub OAuth, JWT (python-jose) |
| Deployment | Vercel (frontend), Render (backend) |

---

## Architecture / Request Flow

```
Client
  → Logging middleware       (latency timing)
    → API Key middleware     (authenticate + load tenant from cache)
      → Rate Limiter         (global limit check → route limit check via Redis Lua)
        → Proxy Handler      (score backends → pick best → forward → failover)
          → Upstream Backend
```

The middleware stack runs in this order on every proxied request. Any layer can short-circuit and return a response without the request reaching the upstream.

The proxy handler scores each backend using a composite of average latency, recent failure rate, and current load — backends with open circuit breakers are skipped entirely.

Route and rate limit configuration is loaded from PostgreSQL into an in-memory cache on startup and refreshed every 10 seconds in the background, so the critical path never waits on a database query.

---

## Dashboard Features

The React frontend provides a full management interface:

- **Projects** — create and manage isolated projects; view per-project aggregated metrics (total requests, avg latency, healthy backends, blocked requests)
- **Routes** — create routes within a project; view per-route status (healthy / degraded / offline based on backend health), request counts, and latency
- **Backends** — add and remove backend URLs per route; view per-backend health status, circuit breaker state, request counts, and average latency
- **API Keys** — generate API keys with custom names; configure and edit global rate limits (refill rate, capacity) inline in the table; copy the generated key once on creation
- **Route Monitoring** — time-series request traffic chart with rate limit threshold reference line; allowed/blocked/failed request breakdown; load balancer distribution chart across backends; per-backend expandable monitoring panels with circuit state and latency
- **Sidebar navigation** — collapsible sidebar with sections for Routes, API Keys, and Settings per project

---

## Security & Reliability

- API keys are stored hashed; only a preview prefix is shown in the UI after creation
- Rate limits are enforced atomically in Redis — no race conditions under concurrent load
- Rate limiter fails open if Redis is unavailable (requests pass through rather than blocking the API)
- Circuit breakers prevent traffic from reaching repeatedly failing backends
- Health checker runs independently and deprioritizes backends before the circuit fully opens
- JWT cookies are `HttpOnly`, `Secure`, and `SameSite=None`
- All ownership checks are enforced at the service layer — a user cannot read or modify another user's projects, routes, or keys

---

## Infrastructure Components

**PostgreSQL** stores the persistent state: users, tenants (projects), routes, backends, API keys, global rate limits, and route-level rate limits.

**Redis** stores all ephemeral operational state:
- Token bucket state per API key and per route (rate limiting)
- Request metrics and time-series data per route
- Per-backend request/success/failure counters and latency (EMA)
- Circuit breaker state per backend
- Health check status per backend

**Cache layer** — on gateway startup, all routes, backends, rate limits, and API keys are loaded into a Python dict. The gateway middleware reads exclusively from this cache; no database queries happen in the hot path.

---

## API Capabilities

The Control API exposes:

- `POST /auth/github/login` — initiate GitHub OAuth
- `GET /auth/github/callback` — OAuth callback, sets auth cookie
- `GET /auth/me` — return current user info
- `GET/POST/DELETE /api/projects` — project management
- `GET/POST/DELETE /api/routes/{project_id}` — route management
- `GET /api/routes/detail/{route_id}` — full route detail with metrics and backend state
- `GET/POST/DELETE /api/backends/{route_id}` — backend management
- `GET/POST/DELETE /api/keys/{project_id}` — API key management
- `POST /api/rate-limit/global/{api_key_id}` — set global rate limit
- `POST /api/rate-limit/route/{route_id}` — set route-level rate limit
- `GET /metrics/route/{route_id}` — route traffic metrics
- `GET /metrics/backends/{route_id}` — per-backend metrics
- `GET /metrics/projects` — project-level aggregated overview

The Gateway accepts:

```
GET/POST/PUT/PATCH/DELETE/OPTIONS /proxy/{route_name}/{path}
x-api-key: <your_api_key>
```

---

## Deployment

- Frontend is deployed on Vercel with SPA rewrite rules (`vercel.json`)
- Backend (both control and gateway apps) runs on Render
- Environment variables configure database URL, Redis URL, GitHub OAuth credentials, JWT secret, and frontend redirect URLs
- The two FastAPI apps share the same codebase but are mounted and started separately

---

## Planned Improvements

- Retry logic on upstream 503/504 with exponential backoff
- Weighted backend routing (send proportionally more traffic to faster backends)
- Webhook support for alerting on circuit opens or health degradation
- Prometheus-compatible metrics endpoint
- Admin UI for project member management
- Per-route path rewriting rules

---

## License

MIT — see [LICENSE](./LICENSE)