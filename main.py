from fastapi import FastAPI

from middlewares.api_key import auth_middleware
from middlewares.rate_limiter import rate_limiter
from middlewares.logging import middleman
from services.proxy import proxy_handler
from core.health import health_checker
import asyncio
from contextlib import asynccontextmanager
from db.connect import db
from core.repository import get_tenant_by_api_key
from core.cache_loader import load_all_cache, cache_refresher
from core.metrics import get_metrics
from core.redis_client import r

from routes.user_auth_route import router as auth_router
from middlewares.user_auth import user_middleware

from routes.project_route import router as project_router

from routes.api_key_route import router as api_key_router
from routes.rate_limit_route import router as rate_limit_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # start background task

    #database connection
    await db.connect()
    print("db connected")
    task = asyncio.create_task(health_checker())

    await load_all_cache()
    asyncio.create_task(cache_refresher())
    
    yield
    
    #db disconnect
    await db.disconnect()
    print("db disconnected")

    # cleanup on shutdown
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

app = FastAPI(lifespan=lifespan)

@app.get("/test-tenant")
async def test_tenant():
    data = await get_tenant_by_api_key("test123")
    return data

@app.get("/metrics")
async def metrics():
    return get_metrics()

@app.get("/backend-metrics")
async def get_backend_metrics():
    keys = r.keys("backend:*")

    result = {}

    for key in keys:
        key_str = key.decode() if isinstance(key, bytes) else key

        # ✅ NEW FORMAT: backend:route_id:backend_id
        try:
            _, route_id, backend_id = key_str.split(":")
        except ValueError:
            continue  # skip malformed keys

        data = r.hgetall(key)

        clean_data = {
            (k.decode() if isinstance(k, bytes) else k):
            (v.decode() if isinstance(v, bytes) else v)
            for k, v in data.items()
        }

        if route_id not in result:
            result[route_id] = {}

        result[route_id][backend_id] = clean_data

    return result


app.include_router(auth_router, prefix="/auth")
app.include_router(project_router, prefix="/api/projects")
app.include_router(api_key_router, prefix="/api/keys")
app.include_router(rate_limit_router, prefix="/api/rate-limit")

app.middleware("http")(rate_limiter)
app.middleware("http")(auth_middleware)
app.middleware("http")(middleman)
app.middleware("http")(user_middleware)


app.api_route(
    "/proxy/{pref}/{full_path:path}",
    methods=["GET","POST","PUT","PATCH","DELETE"]
)(proxy_handler)