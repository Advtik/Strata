from db.connect import db

async def get_tenant_by_api_key(api_key: str):
    if db.pool is None:
        raise RuntimeError("Database not connected")

    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT t.id, t.name
            FROM api_keys ak
            JOIN tenants t ON ak.tenant_id = t.id
            WHERE ak.key = $1
        """, api_key)

        if row is None:
            return None

        return {
            "id": row["id"],
            "name": row["name"]
        }
    
async def get_all_rate_limits():
    if db.pool is None:
        raise RuntimeError("DB not connected")

    async with db.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT ak.key, rl.refill_rate, rl.capacity
            FROM api_keys ak
            JOIN rate_limits rl ON ak.id = rl.api_key_id
        """)

        result = {}

        for row in rows:
            result[row["key"]] = {
                "refill_rate": row["refill_rate"],
                "capacity": row["capacity"]
            }

        return result

async def get_routes_for_tenant(tenant_id: int):
    if db.pool is None:
        raise RuntimeError("DB not connected")

    async with db.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT r.name AS route_name, b.url
            FROM routes r
            JOIN backends b ON r.id = b.route_id
            WHERE r.tenant_id = $1
        """, tenant_id)

        routes = {}

        for row in rows:
            route_name = row["route_name"]

            if route_name not in routes:
                routes[route_name] = {
                    "backends": []
                }

            routes[route_name]["backends"].append({
                "url": row["url"]
            })

        return routes
    

async def get_all_backends():
    if db.pool is None:
        raise RuntimeError("DB not connected")

    async with db.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT r.tenant_id, r.name as route_name, b.url
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
                result[tenant_id][route_name] = []

            result[tenant_id][route_name].append({
                "url": row["url"]
            })

        return result
    

async def get_all_api_keys():
    if db.pool is None:
        raise RuntimeError("DB not connected")
    
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT ak.key, t.id, t.name
            FROM api_keys ak
            JOIN tenants t ON ak.tenant_id = t.id
        """)

        result = {}

        for row in rows:
            result[row["key"]] = {
                "id": row["id"],
                "name": row["name"]
            }

        return result