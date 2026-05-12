import time

from core.redis_client import r

FAILURE_THRESHOLD = 3
COOLDOWN_TIME = 30
HALF_OPEN_MAX_CALLS = 2


def _key(
    route_id: int,
    backend_id: int
):

    return f"cb:{route_id}:{backend_id}"


async def get_state(
    route_id: int,
    backend_id: int
):

    key = _key(
        route_id,
        backend_id
    )

    data = await r.hgetall(key)

    if not data:

        state = {
            "failures": 0,
            "state": "CLOSED",
            "opened_at": 0,
            "trial_calls": 0,
            "trial_success": 0
        }

        await r.hset(
            key,
            mapping={
                "failures": 0,
                "state": "CLOSED",
                "opened_at": 0,
                "trial_calls": 0,
                "trial_success": 0
            }
        )

        return state

    return {
        "failures": int(
            data.get("failures", 0)
        ),

        "state": data.get(
            "state",
            "CLOSED"
        ),

        "opened_at": float(
            data.get("opened_at", 0)
        ),

        "trial_calls": int(
            data.get("trial_calls", 0)
        ),

        "trial_success": int(
            data.get("trial_success", 0)
        )
    }


async def can_request(
    route_id: int,
    backend_id: int
):

    key = _key(
        route_id,
        backend_id
    )

    state = await get_state(
        route_id,
        backend_id
    )

    if state["state"] == "CLOSED":

        return True

    if state["state"] == "OPEN":

        if (
            time.time() -
            state["opened_at"]
        ) > COOLDOWN_TIME:

            print(
                "Moving to HALF_OPEN:",
                key
            )

            await r.hset(
                key,
                mapping={
                    "state": "HALF_OPEN",
                    "trial_calls": 0,
                    "trial_success": 0
                }
            )

            return True

        else:

            return False

    if state["state"] == "HALF_OPEN":

        if (
            state["trial_calls"] <
            HALF_OPEN_MAX_CALLS
        ):

            await r.hincrby(
                key,
                "trial_calls",
                1
            )

            return True

        else:

            if (
                time.time() -
                state["opened_at"]
            ) > COOLDOWN_TIME:

                return True

            else:

                await r.hset(
                    key,
                    mapping={
                        "state": "OPEN",
                        "opened_at": time.time(),
                    }
                )

                return False

    return True


async def record_success(
    route_id: int,
    backend_id: int
):

    key = _key(
        route_id,
        backend_id
    )

    state = await get_state(
        route_id,
        backend_id
    )

    if state["state"] == "HALF_OPEN":

        new_success = await r.hincrby(
            key,
            "trial_success",
            1
        )

        if (
            new_success >=
            HALF_OPEN_MAX_CALLS
        ):

            await r.hset(
                key,
                mapping={
                    "failures": 0,
                    "state": "CLOSED",
                    "trial_calls": 0,
                    "trial_success": 0
                }
            )

        return

    await r.hset(
        key,
        "failures",
        0
    )


async def record_failure(
    route_id: int,
    backend_id: int
):

    key = _key(
        route_id,
        backend_id
    )

    state = await get_state(
        route_id,
        backend_id
    )

    if state["state"] == "HALF_OPEN":

        await r.hset(
            key,
            mapping={
                "state": "OPEN",
                "opened_at": time.time(),
                "trial_calls": 0,
                "trial_success": 0
            }
        )

        return

    failures = await r.hincrby(
        key,
        "failures",
        1
    )

    if failures >= FAILURE_THRESHOLD:

        print(
            "Circuit OPENED:",
            key
        )

        await r.hset(
            key,
            mapping={
                "state": "OPEN",
                "opened_at": time.time()
            }
        )