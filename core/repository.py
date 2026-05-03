import secrets
from db.connect import db


# TENANT 
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


# RATE LIMITS (UPDATED → route_id)
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


# ROUTES FOR TENANT 
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


# ALL BACKENDS (UPDATED)
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




# ----------------------------
# API KEYS
# ----------------------------

async def create_api_key_repo(project_id: int):
    key = secrets.token_urlsafe(32)

    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO api_keys (tenant_id, key)
            VALUES ($1, $2)
            RETURNING id, key
            """,
            project_id,
            key
        )

    return row


async def get_api_keys_repo(project_id: int):
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, key
            FROM api_keys
            WHERE tenant_id = $1
            ORDER BY id DESC
            """,
            project_id
        )
    return rows


async def delete_api_key_repo(key_id: int):
    async with db.pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM api_keys WHERE id = $1",
            key_id
        )


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
    

# ----------------------------
# PROJECTS
# ----------------------------

async def create_project_repo(user_id: int, name: str):
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO tenants (name, user_id)
            VALUES ($1, $2)
            RETURNING id, name
            """,
            name,
            user_id
        )
        return row


async def get_projects_repo(user_id: int):
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name
            FROM tenants
            WHERE user_id = $1
            ORDER BY id DESC
            """,
            user_id
        )
        return rows
    

# ----------------------------
# OWNERSHIP CHECKS
# ----------------------------

async def get_project_owner(project_id: int):
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id FROM tenants WHERE id = $1",
            project_id
        )
        return row


async def get_key_project(key_id: int):
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT tenant_id FROM api_keys WHERE id = $1",
            key_id
        )
        return row


async def count_api_keys(project_id: int):
    async with db.pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM api_keys WHERE tenant_id = $1",
            project_id
        )
        return count
    
async def get_api_key_owner(api_key_id: int):
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT t.user_id
            FROM api_keys ak
            JOIN tenants t ON ak.tenant_id = t.id
            WHERE ak.id = $1
            """,
            api_key_id
        )
        return row
    
async def get_route_owner(route_id: int):
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT t.user_id
            FROM routes r
            JOIN tenants t ON r.tenant_id = t.id
            WHERE r.id = $1
            """,
            route_id
        )
        return row

# ----------------------------
# RATE LIMITS
# ----------------------------

async def set_global_rate_limit(api_key_id: int, capacity: int, refill_rate: float):
    async with db.pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO rate_limits (api_key_id, capacity, refill_rate)
            VALUES ($1, $2, $3)
            ON CONFLICT (api_key_id)
            DO UPDATE SET capacity = $2, refill_rate = $3
            """,
            api_key_id,
            capacity,
            refill_rate
        )

async def get_global_rate_limit(api_key_id: int):
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT capacity, refill_rate
            FROM rate_limits
            WHERE api_key_id = $1
            """,
            api_key_id
        )
        return row

async def set_route_rate_limit(route_id: int, capacity: int, refill_rate: float):
    async with db.pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO route_rate_limits (route_id, capacity, refill_rate)
            VALUES ($1, $2, $3)
            ON CONFLICT (route_id)
            DO UPDATE SET capacity = $2, refill_rate = $3
            """,
            route_id,
            capacity,
            refill_rate
        )

async def get_route_rate_limit(route_id: int):
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT capacity, refill_rate
            FROM route_rate_limits
            WHERE route_id = $1
            """,
            route_id
        )
        return row
