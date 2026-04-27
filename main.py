from fastapi import FastAPI

from middlewares.auth import auth_middleware
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

app.middleware("http")(rate_limiter)
app.middleware("http")(auth_middleware)
app.middleware("http")(middleman)


app.api_route(
    "/proxy/{pref}/{full_path:path}",
    methods=["GET","POST","PUT","PATCH","DELETE"]
)(proxy_handler)