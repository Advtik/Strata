import math
import random
from typing import Dict

from core.redis_client import r

EXPLORE = 150.0
FAILURE_WEIGHT = 50
LOAD_WEIGHT = 5
DECAY = 0.9


def _get_key(
    route_id: int,
    backend_id: int
) -> str:

    return f"backend:{route_id}:{backend_id}"


async def init_backend(
    route_id: int,
    backend_id: int
) -> None:

    key = _get_key(
        route_id,
        backend_id
    )

    exists = await r.exists(key)

    if not exists:

        await r.hset(
            key,
            mapping={
                "requests": 0,
                "successes": 0,
                "failures": 0,
                "avg_latency": 0.0,
                "recent_requests": 0.0,
                "recent_failures": 0.0,
            }
        )


async def record_backend_success(
    route_id: int,
    backend_id: int,
    latency: float
) -> None:

    key = _get_key(
        route_id,
        backend_id
    )

    await init_backend(
        route_id,
        backend_id
    )

    await r.hincrby(
        key,
        "requests",
        1
    )

    await r.hincrby(
        key,
        "successes",
        1
    )

    await r.hincrbyfloat(
        key,
        "recent_requests",
        1.0
    )

    ALPHA = 0.2

    raw = await r.hget(
        key,
        "avg_latency"
    )

    avg_latency = (
        float(raw)
        if raw is not None
        else 0.0
    )

    if avg_latency == 0:

        new_latency = latency

    else:

        new_latency = (
            (1 - ALPHA) * avg_latency
            + ALPHA * latency
        )

    await r.hset(
        key,
        "avg_latency",
        str(new_latency)
    )


async def record_backend_failure(
    route_id: int,
    backend_id: int
) -> None:

    key = _get_key(
        route_id,
        backend_id
    )

    await init_backend(
        route_id,
        backend_id
    )

    await r.hincrby(
        key,
        "requests",
        1
    )

    await r.hincrby(
        key,
        "failures",
        1
    )

    await r.hincrbyfloat(
        key,
        "recent_requests",
        1.0
    )

    await r.hincrbyfloat(
        key,
        "recent_failures",
        1.0
    )


async def get_backend_score(
    route_id: int,
    backend_id: int
) -> float:

    key = _get_key(
        route_id,
        backend_id
    )

    exists = await r.exists(key)

    if not exists:

        return -EXPLORE

    m: Dict[str, str] = await r.hgetall(key)

    def to_int(
        val,
        default=0
    ):

        try:
            return int(val)

        except Exception:
            return default

    def to_float(
        val,
        default=0.0
    ):

        try:
            return float(val)

        except Exception:
            return default

    requests = to_int(
        m.get("requests")
    )

    avg_latency = to_float(
        m.get("avg_latency"),
        0.0
    )

    recent_requests = to_float(
        m.get("recent_requests"),
        0.0
    )

    recent_failures = to_float(
        m.get("recent_failures"),
        0.0
    )

    recent_requests = round(
        recent_requests * DECAY,
        6
    )

    recent_failures = round(
        recent_failures * DECAY,
        6
    )

    await r.hset(
        key,
        mapping={
            "recent_requests": str(recent_requests),
            "recent_failures": str(recent_failures),
        }
    )

    exploration_bonus = (
        EXPLORE /
        math.sqrt(requests + 1)
    )

    if recent_requests > 0.05:

        recent_failure_rate = min(
            recent_failures /
            recent_requests,
            1.0
        )

    else:

        recent_failure_rate = 0.0

    failure_penalty = (
        recent_failure_rate * 300.0
    )

    load_penalty = (
        recent_requests * 0.5
    )

    score = (
        avg_latency +
        failure_penalty +
        load_penalty -
        exploration_bonus
    )

    return score


async def pick_best_backend(
    route_id: int,
    backends: list
):

    if not backends:

        return None

    best_backend = None

    best_score = float("inf")

    for backend in backends:

        backend_id = backend["id"]

        score = await get_backend_score(
            route_id,
            backend_id
        )

        score += random.uniform(
            0.0,
            1e-4
        )

        if score < best_score:

            best_score = score

            best_backend = backend

    return best_backend