from fastapi import FastAPI

from middlewares.auth import auth_middleware
from middlewares.rate_limiter import rate_limiter
from middlewares.logging import middleman
from services.proxy import proxy_handler

app = FastAPI()

app.middleware("http")(rate_limiter)
app.middleware("http")(auth_middleware)
app.middleware("http")(middleman)

app.api_route(
    "/proxy/{pref}/{full_path:path}",
    methods=["GET","POST","PUT","PATCH","DELETE"]
)(proxy_handler)