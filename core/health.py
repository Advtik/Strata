import asyncio
import httpx
from core.config import routes

health_status = {}

FAILURE_THRESHOLD = 3
SUCCESS_THRESHOLD = 2


async def check_backend(backend):
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            await client.get(backend)
        return True
    except Exception:
        return False


async def health_checker():
    global health_status

    while True:
        for route_name, route in routes.items():
            backends = route["backends"]

            if route_name not in health_status:
                health_status[route_name] = {}

            for backend in backends:

                if backend not in health_status[route_name]:
                    health_status[route_name][backend] = {
                        "healthy": True,
                        "failures": 0,
                        "successes": 0
                    }

                state = health_status[route_name][backend]

                is_healthy = await check_backend(backend)

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

        await asyncio.sleep(10)