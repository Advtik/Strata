from fastapi import Request, Response
from core.config import tenants


#auth middleware in place
async def auth_middleware(request:Request, call_next):
    key_header = request.headers.get("x-api-key")

    if key_header is None:
        return Response(content="Missing API Key", status_code=401)

    tenant = tenants.get(key_header)

    if tenant is None:
        return Response(content="Invalid API Key", status_code=401)
    
    print(tenant["name"])
    request.state.tenant = tenant
    request.state.api_key=key_header
    response = await call_next(request)
    return response

