import asyncio
import httpx

from core.repository import get_all_backends
from db.connect import db

health_status = {}

FAILURE_THRESHOLD = 3
SUCCESS_THRESHOLD = 2

client = httpx.AsyncClient(timeout=10.0)


async def check_backend(backend):
    try:
        await client.get(backend['url'])
        return True
    except Exception:
        return False


async def health_checker():
    global health_status

    while True:
        try:
            if db.pool is None:
                print("DB not ready, skipping health check...")
                await asyncio.sleep(5)
                continue

            backend_map = await get_all_backends()

            for tenant_id, routes in backend_map.items():

                for route_name, backends in routes.items():  # ✅ FIXED

                    if route_name not in health_status:
                        health_status[route_name] = {}

                    tasks = [check_backend(b) for b in backends]
                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    for backend, result in zip(backends, results):
                        backend_url = backend['url']

                        if backend_url not in health_status[route_name]:
                            health_status[route_name][backend_url] = {
                                "healthy": True,
                                "failures": 0,
                                "successes": 0
                            }

                        state = health_status[route_name][backend_url]

                        is_healthy = False if isinstance(result, Exception) else result

                        if not is_healthy:
                            state["failures"] += 1
                            state["successes"] = 0

                            if state["failures"] >= FAILURE_THRESHOLD:
                                state["healthy"] = False
                        else:
                            state["successes"] += 1
                            state["failures"] = 0

                            if state["successes"] >= SUCCESS_THRESHOLD:
                                state["healthy"] = True

            print("health:", health_status)

        except Exception as e:
            print("Health checker error:", e)

        await asyncio.sleep(30)