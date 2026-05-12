import asyncio
import httpx

from core.repository import get_all_backends
from db.connect import db
from core.redis_client import r

FAILURE_THRESHOLD = 3
SUCCESS_THRESHOLD = 2

client = httpx.AsyncClient(timeout=10.0)


# NOW USE IDS
def _get_key(route_id: int, backend_id: int) -> str:
    return f"health:{route_id}:{backend_id}"


def init_health(route_id: int, backend_id: int):
    key = _get_key(route_id, backend_id)

    if not r.exists(key):
        r.hset(key, mapping={
            "healthy": "0",
            "failures": 0,
            "successes": 0
        })


async def check_backend(backend):
    try:
        response=await client.get(backend['url'])
        return 200 <= response.status_code < 400
        return True
    except Exception:
        return False


async def health_checker():
    while True:
        try:
            if db.pool is None:
                print("DB not ready, skipping health check...")
                await asyncio.sleep(5)
                continue

            backend_map = await get_all_backends()

            for tenant_id, routes in backend_map.items():

                for route_name, route_data in routes.items():

                    route_id = route_data["route_id"]
                    backends = route_data["backends"]

                    tasks = [check_backend(b) for b in backends]
                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    for backend, result in zip(backends, results):
                        backend_id = backend["id"]
                        key = _get_key(route_id, backend_id)

                        init_health(route_id, backend_id)

                        is_healthy = False if isinstance(result, Exception) else result

                        if not is_healthy:
                            r.hincrby(key, "failures", 1)
                            r.hset(key, "successes", 0)

                            failures = int(r.hget(key, "failures") or 0)

                            if failures >= FAILURE_THRESHOLD:
                                r.hset(key, "healthy", "0")

                        else:
                            r.hincrby(key, "successes", 1)
                            r.hset(key, "failures", 0)

                            successes = int(r.hget(key, "successes") or 0)

                            if successes >= SUCCESS_THRESHOLD:
                                r.hset(key, "healthy", "1")

            print("health updated")

        except Exception as e:
            print("Health checker error:", e)

        await asyncio.sleep(30)


#  HELPER
def is_backend_healthy(route_id: int, backend_id: int) -> bool:
    key = _get_key(route_id, backend_id)
    val = r.hget(key, "healthy")

    return val == "1"