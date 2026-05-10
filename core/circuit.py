import time
from core.redis_client import r

FAILURE_THRESHOLD = 3
COOLDOWN_TIME = 10   # seconds
HALF_OPEN_MAX_CALLS = 2


def _key(route_id: int, backend_id: int):
    return f"cb:{route_id}:{backend_id}"


def get_state(route_id: int, backend_id: int):
    key = _key(route_id, backend_id)

    data = r.hgetall(key)

    if not data:
        # initialize (same logic)
        state = {
            "failures": 0,
            "state": "CLOSED",
            "opened_at": 0,
            "trial_calls": 0,
            "trial_success": 0
        }

        r.hset(key, mapping={
            "failures": 0,
            "state": "CLOSED",
            "opened_at": 0,
            "trial_calls": 0,
            "trial_success": 0
        })

        return state

    # decode + cast
    return {
        "failures": int(data.get("failures", 0)),
        "state": data.get("state", "CLOSED"),
        "opened_at": float(data.get("opened_at", 0)),
        "trial_calls": int(data.get("trial_calls", 0)),
        "trial_success": int(data.get("trial_success", 0))
    }


def can_request(route_id: int, backend_id: int):
    key = _key(route_id, backend_id)
    state = get_state(route_id, backend_id)

    print("circuit_state", key, state)

    if state["state"] == "CLOSED":
        return True

    if state["state"] == "OPEN":
        if time.time() - state["opened_at"] > COOLDOWN_TIME:
            print("Moving to HALF_OPEN:", key)

            r.hset(key, mapping={
                "state": "HALF_OPEN",
                "trial_calls": 0,
                "trial_success": 0
            })

            return True
        else:
            return False

    if state["state"] == "HALF_OPEN":
        if state["trial_calls"] < HALF_OPEN_MAX_CALLS:
            r.hincrby(key, "trial_calls", 1)
            return True
        else:
            if time.time() - state["opened_at"] > COOLDOWN_TIME:
                return True
            else:
                r.hset(key, mapping={
                    "state": "OPEN",
                    "opened_at": time.time(),
                })
                return False

        return True


def record_success(route_id: int, backend_id: int):
    key = _key(route_id, backend_id)
    state = get_state(route_id, backend_id)

    if state["state"] == "HALF_OPEN":
        new_success = r.hincrby(key, "trial_success", 1)

        print(f"HALF_OPEN success {new_success}/{HALF_OPEN_MAX_CALLS}:", key)

        if new_success >= HALF_OPEN_MAX_CALLS:
            print("Circuit CLOSED (recovered):", key)

            r.hset(key, mapping={
                "failures": 0,
                "state": "CLOSED",
                "trial_calls": 0,
                "trial_success": 0
            })

        return

    # CLOSED → reset failures
    r.hset(key, "failures", 0)


def record_failure(route_id: int, backend_id: int):
    key = _key(route_id, backend_id)
    state = get_state(route_id, backend_id)

    if state["state"] == "HALF_OPEN":
        print("HALF_OPEN failed → OPEN again:", key)

        r.hset(key, mapping={
            "state": "OPEN",
            "opened_at": time.time(),
            "trial_calls": 0,
            "trial_success": 0
        })

        return

    failures = r.hincrby(key, "failures", 1)

    if failures >= FAILURE_THRESHOLD:
        print("Circuit OPENED:", key)

        r.hset(key, mapping={
            "state": "OPEN",
            "opened_at": time.time()
        })