from fastapi import Request, HTTPException
from services.rate_limit_service import (
    set_global_rate_limit_service,
    set_route_rate_limit_service,
    get_global_rate_limit_service,
    get_route_rate_limit_service
)
from core.cache_loader import load_rate_limits_cache


async def set_global_rate_limit_controller(request: Request, api_key_id: int):
    user = request.state.user

    try:
        data = await request.json()

        await set_global_rate_limit_service(user, api_key_id, data)

        # ✅ refresh cache immediately
        await load_rate_limits_cache()

        return {"message": "Global rate limit set"}

    except Exception as e:
        raise HTTPException(400, str(e))
    

async def get_global_rate_limit_controller(request, api_key_id):
    user = request.state.user

    try:
        limit = await get_global_rate_limit_service(user, api_key_id)

        if not limit:
            return {"message": "No rate limit found"}

        return {
            "capacity": limit["capacity"],
            "refill_rate": limit["refill_rate"]
        }

    except Exception as e:
        raise HTTPException(400, str(e))


async def set_route_rate_limit_controller(request: Request, route_id: int):
    user = request.state.user

    try:
        data = await request.json()

        await set_route_rate_limit_service(user, route_id, data)

        # ✅ refresh cache immediately
        await load_rate_limits_cache()

        return {"message": "Route rate limit set"}

    except Exception as e:
        raise HTTPException(400, str(e))
    
async def get_route_rate_limit_controller(request, route_id: int):
    user = request.state.user

    try:
        limit = await get_route_rate_limit_service(user, route_id)

        if not limit:
            return {"message": "No route-specific limit (using global)"}

        return {
            "capacity": limit["capacity"],
            "refill_rate": limit["refill_rate"]
        }

    except Exception as e:
        raise HTTPException(400, str(e))