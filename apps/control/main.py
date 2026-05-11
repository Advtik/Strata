from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import os
from dotenv import load_dotenv

load_dotenv()

from contextlib import asynccontextmanager
from db.connect import db

from routes.user_auth_route import router as auth_router
from routes.project_route import router as project_router
from routes.api_key_route import router as api_key_router
from routes.rate_limit_route import router as rate_limit_router
from routes.routes_route import router as route_router
from routes.backend_route import router as backend_router
from routes.metrics_route import router as metrics_router

from middlewares.user_auth import user_middleware
@asynccontextmanager
async def lifespan(app: FastAPI):

    await db.connect()
    print("control db connected")

    yield

    await db.disconnect()
    print("control db disconnected")

control_app = FastAPI(lifespan=lifespan)

control_app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        os.getenv("FRONTEND_URL"),
        os.getenv("PRODUCTION_FRONTEND_URL")
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

control_app.include_router(auth_router, prefix="/auth")
control_app.include_router(project_router, prefix="/api/projects")
control_app.include_router(api_key_router, prefix="/api/keys")
control_app.include_router(rate_limit_router, prefix="/api/rate-limit")
control_app.include_router(route_router, prefix="/api/routes")
control_app.include_router(backend_router, prefix="/api/backends")
control_app.include_router(metrics_router, prefix="/metrics")

control_app.middleware("http")(user_middleware)

@control_app.get("/")
async def root():
    return {"status": "healthy"}