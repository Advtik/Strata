from db.connect import db


# ------------------------
# TENANT (no change)
# ------------------------
async def get_tenant_by_api_key(api_key: str):
    if db.pool is None:
        raise RuntimeError("Database not connected")

    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT 
                t.id as tenant_id,
                t.name,
                ak.id as api_key_id
            FROM api_keys ak
            JOIN tenants t ON ak.tenant_id = t.id
            WHERE ak.key = $1
        """, api_key)

        if row is None:
            return None

        return {
            "tenant_id": row["tenant_id"],
            "name": row["name"],
            "api_key_id": row["api_key_id"]
        }


# ------------------------
# RATE LIMITS (UPDATED → route_id)
# ------------------------
async def get_all_rate_limits():
    if db.pool is None:
        raise RuntimeError("DB not connected")

    async with db.pool.acquire() as conn:

        # GLOBAL
        global_rows = await conn.fetch("""
            SELECT ak.key, rl.refill_rate, rl.capacity
            FROM api_keys ak
            JOIN rate_limits rl ON ak.id = rl.api_key_id
        """)

        # ROUTE LEVEL (IMPORTANT CHANGE)
        route_rows = await conn.fetch("""
            SELECT ak.key, r.id as route_id, r.name as route_name,
                   rrl.refill_rate, rrl.capacity
            FROM api_keys ak
            JOIN tenants t ON ak.tenant_id = t.id
            JOIN routes r ON r.tenant_id = t.id
            JOIN route_rate_limits rrl ON r.id = rrl.route_id
        """)

        result = {}

        # GLOBAL
        for row in global_rows:
            result[row["key"]] = {
                "global": {
                    "refill_rate": row["refill_rate"],
                    "capacity": row["capacity"]
                },
                "routes": {}
            }

        # ROUTE (NOW USING route_id)
        for row in route_rows:
            key = row["key"]

            if key not in result:
                continue

            route_id = row["route_id"]

            result[key]["routes"][route_id] = {
                "route_name": row["route_name"],  # optional but useful
                "refill_rate": row["refill_rate"],
                "capacity": row["capacity"]
            }

        return result


# ------------------------
# ROUTES FOR TENANT (UPDATED)
# ------------------------
async def get_routes_for_tenant(tenant_id: int):
    if db.pool is None:
        raise RuntimeError("DB not connected")

    async with db.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT 
                r.id as route_id,
                r.name AS route_name,
                b.id as backend_id,
                b.url
            FROM routes r
            JOIN backends b ON r.id = b.route_id
            WHERE r.tenant_id = $1
        """, tenant_id)

        routes = {}

        for row in rows:
            route_name = row["route_name"]

            if route_name not in routes:
                routes[route_name] = {
                    "route_id": row["route_id"],
                    "backends": []
                }

            routes[route_name]["backends"].append({
                "id": row["backend_id"],
                "url": row["url"]
            })

        return routes


# ------------------------
# ALL BACKENDS (UPDATED)
# ------------------------
async def get_all_backends():
    if db.pool is None:
        raise RuntimeError("DB not connected")

    async with db.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT 
                r.tenant_id,
                r.id as route_id,
                r.name as route_name,
                b.id as backend_id,
                b.url
            FROM routes r
            JOIN backends b ON r.id = b.route_id
        """)

        result = {}

        for row in rows:
            tenant_id = row["tenant_id"]
            route_name = row["route_name"]

            if tenant_id not in result:
                result[tenant_id] = {}

            if route_name not in result[tenant_id]:
                result[tenant_id][route_name] = {
                    "route_id": row["route_id"],
                    "backends": []
                }

            result[tenant_id][route_name]["backends"].append({
                "id": row["backend_id"],
                "url": row["url"]
            })

        return result


# ------------------------
# API KEYS (no change)
# ------------------------
async def get_all_api_keys():
    if db.pool is None:
        raise RuntimeError("DB not connected")

    async with db.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT 
                ak.key,
                ak.id as api_key_id,
                t.id,
                t.name
            FROM api_keys ak
            JOIN tenants t ON ak.tenant_id = t.id
        """)

        result = {}

        for row in rows:
            result[row["key"]] = {
                "tenant_id": row["id"],   # rename for clarity
                "name": row["name"],
                "api_key_id": row["api_key_id"]
            }

        return result