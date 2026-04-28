from fastapi import Request, Response
from core.cache import cache


# auth middleware
async def auth_middleware(request: Request, call_next):
    key_header = request.headers.get("x-api-key")

    if key_header is None:
        return Response(content="Missing API Key", status_code=401)

    tenant = cache["tenants"].get(key_header)

    if tenant is None:
        return Response(content="Invalid API Key", status_code=401)

    print(tenant["name"])

    # ✅ structured state (clean)
    request.state.tenant = {
        "id": tenant["tenant_id"],
        "name": tenant["name"]
    }

    request.state.api_key = key_header

    # 🔥 IMPORTANT (NEW)
    request.state.api_key_id = tenant["api_key_id"]

    response = await call_next(request)
    return response