import time

circuit_state = {}

FAILURE_THRESHOLD = 3
COOLDOWN_TIME = 10   # seconds
HALF_OPEN_MAX_CALLS = 2


def get_state(backend):
    backend_url = backend['url']   # ✅ extract once

    if backend_url not in circuit_state:
        circuit_state[backend_url] = {
            "failures": 0,
            "state": "CLOSED",
            "opened_at": None,
            "trial_calls": 0,
            "trial_success": 0
        }

    return circuit_state[backend_url]   # ✅ correct return


def can_request(backend):
    backend_url = backend["url"]
    state = get_state(backend)

    print("circuit_state", backend_url, state)

    if state["state"] == "CLOSED":
        return True

    if state["state"] == "OPEN":
        if time.time() - state["opened_at"] > COOLDOWN_TIME:
            print("Moving to HALF_OPEN:", backend_url)
            state["state"] = "HALF_OPEN"
            state["trial_calls"] = 0
            state["trial_success"] = 0
            return True
        else:
            return False

    if state["state"] == "HALF_OPEN":
        if state["trial_calls"] < HALF_OPEN_MAX_CALLS:
            state["trial_calls"] += 1
            return True
        else:
            return False

    return True


def record_success(backend):
    backend_url = backend["url"]
    state = get_state(backend)

    if state["state"] == "HALF_OPEN":
        state["trial_success"] += 1

        print(f"HALF_OPEN success {state['trial_success']}/{HALF_OPEN_MAX_CALLS}:", backend_url)

        if state["trial_success"] >= HALF_OPEN_MAX_CALLS:
            print("Circuit CLOSED (recovered):", backend_url)
            state["failures"] = 0
            state["state"] = "CLOSED"
            state["opened_at"] = None
            state["trial_calls"] = 0
            state["trial_success"] = 0

        return

    state["failures"] = 0


def record_failure(backend):
    backend_url = backend["url"]
    state = get_state(backend)

    if state["state"] == "HALF_OPEN":
        print("HALF_OPEN failed → OPEN again:", backend_url)
        state["state"] = "OPEN"
        state["opened_at"] = time.time()
        state["trial_calls"] = 0
        state["trial_success"] = 0
        return

    state["failures"] += 1

    if state["failures"] >= FAILURE_THRESHOLD:
        print("Circuit OPENED:", backend_url)
        state["state"] = "OPEN"
        state["opened_at"] = time.time()