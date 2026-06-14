import asyncio

from core.repository import (
    get_all_backends,
    get_all_rate_limits,
    get_all_api_keys
)
from core.cache import cache
from db.connect import db



async def load_routes_cache():
    if db.pool is None:
        print("DB not ready, retrying...")
        return

    backend_map = await get_all_backends()

    routes_cache = {}

    for tenant_id, routes in backend_map.items():
        routes_cache[tenant_id] = {}

        for route_name, route_data in routes.items():
            routes_cache[tenant_id][route_name] = {
                "route_id": route_data["route_id"],
                "backends": route_data["backends"]
            }

    cache["routes"] = routes_cache

    


async def load_rate_limits_cache():
    if db.pool is None:
        print("DB not ready, retrying...")
        return

    rate_limits = await get_all_rate_limits()

    cache["rate_limits"] = rate_limits

    


async def load_tenants_cache():
    if db.pool is None:
        return

    tenants = await get_all_api_keys()

    # {
    #   api_key: {
    #       tenant_id,
    #       name,
    #       api_key_id
    #   }
    # }
    cache["tenants"] = tenants

    


async def load_all_cache():
    await load_routes_cache()
    await load_rate_limits_cache()
    await load_tenants_cache()



async def cache_refresher():
    while True:
        try:
            await load_all_cache()
        except Exception as e:
            print("Cache refresh failed:", e)

        await asyncio.sleep(300)