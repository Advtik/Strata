from fastapi import FastAPI

import asyncio

from contextlib import asynccontextmanager


from db.connect import db

from core.health import health_checker

from core.cache_loader import (
    load_all_cache,
    cache_refresher
)

from middlewares.api_key import auth_middleware
from middlewares.rate_limiter import rate_limiter
from middlewares.logging import middleman
from services.proxy import proxy_handler
from fastapi import Request

@asynccontextmanager
async def lifespan(app: FastAPI):

    await db.connect()
    print("gateway db connected")

    await load_all_cache()

    health_task = asyncio.create_task(
        health_checker()
    )

    cache_task = asyncio.create_task(
        cache_refresher()
    )

    yield

    health_task.cancel()
    cache_task.cancel()

    await asyncio.gather(
        health_task,
        cache_task,
        return_exceptions=True
    )

    await db.disconnect()

    print("gateway db disconnected")


gateway_app = FastAPI(lifespan=lifespan)

gateway_app.router.redirect_slashes = False

@gateway_app.get("/test")
async def test():
    return {"working": True}

gateway_app.middleware("http")(rate_limiter)
gateway_app.middleware("http")(auth_middleware)
gateway_app.middleware("http")(middleman)


@gateway_app.get("/proxy/echo/test")
async def proxy_test():
    return {"ok":True}

@gateway_app.api_route(
    "/proxy/{pref}/{full_path:path}",
    methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"]
)
async def gateway_proxy(
    pref: str,
    full_path: str,
    request: Request
):
    return await proxy_handler(
        pref,
        full_path,
        request
    )



@gateway_app.get("/")
async def root():
    return {"status": "healthy"}