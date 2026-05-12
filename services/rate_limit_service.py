from core.repository import set_global_rate_limit, set_route_rate_limit, get_api_key_owner, get_route_owner, get_global_rate_limit, get_route_rate_limit

# MAX LIMITS (anti abuse)
MAX_CAPACITY = 10000
MAX_REFILL = 1000.0


def clamp_limits(capacity, refill):
    capacity = max(1, min(int(capacity), MAX_CAPACITY))
    refill = max(0.1, min(float(refill), MAX_REFILL))
    return capacity, refill


async def set_global_rate_limit_service(user, api_key_id, data):

    if user is None:
        raise Exception("Not authenticated")

    # ✅ ownership check
    owner = await get_api_key_owner(api_key_id)

    if not owner or owner["user_id"] != user["id"]:
        raise Exception("Not allowed")

    capacity = data.get("capacity")
    refill = data.get("refill_rate")

    if capacity is None or refill is None:
        raise Exception("Missing fields")
    
    if capacity == 0 or refill == 0:
        raise Exception("Cannot be zero")

    capacity, refill = clamp_limits(capacity, refill)

    await set_global_rate_limit(api_key_id, capacity, refill)


async def get_global_rate_limit_service(user, api_key_id):

    if user is None:
        raise Exception("Not authenticated")

    # ownership check
    owner = await get_api_key_owner(api_key_id)

    if not owner or owner["user_id"] != user["id"]:
        raise Exception("Not allowed")

    return await get_global_rate_limit(api_key_id)


async def set_route_rate_limit_service(user, route_id, data):
    if user is None:
        raise Exception("Not authenticated")
    
     # ownership check
    owner = await get_route_owner(route_id)

    if not owner or owner["user_id"] != user["id"]:
        raise Exception("Not allowed")

    capacity = data.get("capacity")
    refill = data.get("refill_rate")

    if capacity is None or refill is None:
        raise Exception("Missing fields")
    
    if capacity == 0 or refill == 0:
        raise Exception("Cannot be zero")

    capacity, refill = clamp_limits(capacity, refill)

    await set_route_rate_limit(route_id, capacity, refill)


async def get_route_rate_limit_service(user, route_id):

    if user is None:
        raise Exception("Not authenticated")

    # ✅ ownership check
    owner = await get_route_owner(route_id)

    if not owner or owner["user_id"] != user["id"]:
        raise Exception("Not allowed")

    return await get_route_rate_limit(route_id)