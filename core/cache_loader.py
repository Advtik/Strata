import asyncio
from importlib.abc import Loader

from core.repository import get_all_backends, get_all_rate_limits,get_all_api_keys
from core.cache import cache
from db.connect import db


# ----------------------------
# ROUTES CACHE LOADER
# ----------------------------
async def load_routes_cache():
    if db.pool is None:
        print("DB not ready, retrying...")
        return

    backend_map = await get_all_backends()

    routes_cache = {}

    for tenant_id, routes in backend_map.items():
        routes_cache[tenant_id] = {}

        for route_name, backends in routes.items():
            routes_cache[tenant_id][route_name] = {
                "backends": backends
            }

    # ✅ atomic replace (important)
    cache["routes"] = routes_cache

    print("Routes cache updated")


# ----------------------------
# RATE LIMIT CACHE LOADER
# ----------------------------
async def load_rate_limits_cache():
    if db.pool is None:
        print("DB not ready, retrying...")
        return

    rate_limits = await get_all_rate_limits()

    # ✅ atomic replace
    cache["rate_limits"] = rate_limits

    print("Rate limits cache updated")


# ------------------------
# TENANT LOADER 
# ------------------------
async def load_tenants_cache():
    if db.pool is None:
        return

    tenants = await get_all_api_keys()
    cache["tenants"] = tenants

    print("Tenants cache updated")


# ----------------------------
# LOAD EVERYTHING
# ----------------------------
async def load_all_cache():
    await load_routes_cache()
    await load_rate_limits_cache()
    await load_tenants_cache() 


# ----------------------------
# BACKGROUND REFRESH LOOP
# ----------------------------
async def cache_refresher():
    while True:
        try:
            await load_all_cache()
        except Exception as e:
            # ❗ VERY IMPORTANT: never let loop crash
            print("Cache refresh failed:", e)

        await asyncio.sleep(10)   # refresh interval