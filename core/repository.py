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
    
async def get_rate_limit_by_api_key(api_key: str):
    if db.pool is None:
        raise RuntimeError("Database not connected")
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT rl.refill_rate, rl.capacity
            FROM api_keys ak
            JOIN rate_limits rl ON ak.id = rl.api_key_id
            WHERE ak.key = $1
        """, api_key)

        if row is None:
            return None

        return {
            "refill_rate": row["refill_rate"],
            "capacity": row["capacity"]
        }
    

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
            SELECT r.name as route_name, b.url
            FROM routes r
            JOIN backends b ON r.id = b.route_id
        """)

        result = {}

        for row in rows:
            route_name = row["route_name"]

            if route_name not in result:
                result[route_name] = []

            result[route_name].append({
                "url": row["url"]
            })

        return result