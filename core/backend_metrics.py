import random
from typing import Dict
from core.redis_client import r


# ID-based key
def _get_key(route_id: int, backend_id: int) -> str:
    return f"backend:{route_id}:{backend_id}"


def init_backend(route_id: int, backend_id: int) -> None:
    key = _get_key(route_id, backend_id)

    if not r.exists(key):
        r.hset(key, mapping={
            "requests": 0,
            "successes": 0,
            "failures": 0,
            "avg_latency": 0.0,
            "recent_requests": 0.0
        })


def record_backend_success(route_id: int, backend_id: int, latency: float) -> None:
    key = _get_key(route_id, backend_id)
    init_backend(route_id, backend_id)

    r.hincrby(key, "requests", 1)
    r.hincrby(key, "successes", 1)

    # float increment
    r.hincrbyfloat(key, "recent_requests", 1.0)

    # EMA latency
    ALPHA = 0.2

    raw = r.hget(key, "avg_latency")
    avg_latency = float(raw) if raw is not None else 0.0

    if avg_latency == 0:
        new_latency = latency
    else:
        new_latency = (1 - ALPHA) * avg_latency + ALPHA * latency

    r.hset(key, "avg_latency", str(new_latency))  # ✅ store as string


def record_backend_failure(route_id: int, backend_id: int) -> None:
    key = _get_key(route_id, backend_id)
    init_backend(route_id, backend_id)

    r.hincrby(key, "requests", 1)
    r.hincrby(key, "failures", 1)

    r.hincrbyfloat(key, "recent_requests", 1.0)


def get_backend_score(route_id: int, backend_id: int) -> float:
    key = _get_key(route_id, backend_id)

    if not r.exists(key):
        return 0.5 + random.random()

    m: Dict[str, str] = r.hgetall(key)

    # safe parsing
    def to_int(val, default=0):
        try:
            return int(val)
        except:
            return default

    def to_float(val, default=0.0):
        try:
            return float(val)
        except:
            return default

    requests = to_int(m.get("requests"))
    successes = to_int(m.get("successes"))
    failures = to_int(m.get("failures"))
    avg_latency = to_float(m.get("avg_latency"), 1.0)
    recent_requests = to_float(m.get("recent_requests"), 0.0)

    if requests == 0:
        return 0.5 + random.random()

    if successes == 0 and failures > 0:
        return float("inf")

    # decay
    recent_requests *= 0.9
    r.hset(key, "recent_requests", str(recent_requests))  # string

    failure_rate = failures / requests if requests > 0 else 0.0

    load_penalty = recent_requests * 0.5
    penalty = 300

    score = avg_latency + (failure_rate * penalty) + load_penalty

    if failures > 0:
        score += 100

    return score


def pick_best_backend(route_id: int, backends: list):
    best_backend = None
    best_score = float("inf")

    for backend in backends:
        backend_id = backend["id"]

        score = get_backend_score(route_id, backend_id)

        if score < best_score:
            best_score = score
            best_backend = backend

    return best_backend