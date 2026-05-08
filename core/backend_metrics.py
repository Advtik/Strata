import math
import random
from typing import Dict
from core.redis_client import r

EXPLORE = 150.0  # UCB exploration strength; tune between 100–300
FAILURE_WEIGHT = 50
LOAD_WEIGHT = 5
DECAY = 0.9


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
            "recent_requests": 0.0,
            "recent_failures": 0.0,   # ← ADD THIS
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
    r.hincrbyfloat(key, "recent_failures", 1.0)   # ← ADD THIS




def get_backend_score(route_id: int, backend_id: int) -> float:
    key = _get_key(route_id, backend_id)

    # Backend has never been seen at all — make it maximally attractive
    # so it gets tried before we judge it.
    if not r.exists(key):
        return -EXPLORE

    m: Dict[str, str] = r.hgetall(key)

    def to_int(val, default=0):
        try:
            return int(val)
        except Exception:
            return default

    def to_float(val, default=0.0):
        try:
            return float(val)
        except Exception:
            return default

    requests        = to_int(m.get("requests"))
    avg_latency     = to_float(m.get("avg_latency"), 0.0)
    recent_requests = to_float(m.get("recent_requests"), 0.0)
    recent_failures = to_float(m.get("recent_failures"), 0.0)

    # Decay the sliding window each scoring pass — same as original,
    # but now applied to both recent counters together.
    recent_requests = round(recent_requests * DECAY, 6)
    recent_failures = round(recent_failures * DECAY, 6)
    r.hset(key, mapping={
        "recent_requests": str(recent_requests),
        "recent_failures":  str(recent_failures),
    })

    # ── Fix 1: UCB exploration bonus ────────────────────────────────────
    # Large when requests is small → unexplored backends look attractive.
    # Shrinks as sqrt(requests) grows → stops interfering once we have data.
    # At 0 requests : 150 / sqrt(1)   = 150  (dominates, backend gets tried)
    # At 9 requests : 150 / sqrt(10)  ≈  47
    # At 99 requests: 150 / sqrt(100) =  15  (minor nudge only)
    # At 999 requests: 150 / sqrt(1000) ≈ 4.7 (effectively negligible)
    exploration_bonus = EXPLORE / math.sqrt(requests + 1)

    # ── Fix 2: windowed failure rate, not cumulative ────────────────────
    # recent_failures decays every call, so a backend that stopped failing
    # will see this rate drift back to 0 automatically — no permanent scar.
    if recent_requests > 0.05:   # guard against near-zero division
        recent_failure_rate = min(recent_failures / recent_requests, 1.0)
    else:
        recent_failure_rate = 0.0

    failure_penalty = recent_failure_rate * 300.0   # 0 when healthy, up to 300
    load_penalty    = recent_requests * 0.5          # same as original

    # Lower score = better backend (same semantics as original).
    # exploration_bonus is subtracted → makes under-explored backends cheaper.
    score = avg_latency + failure_penalty + load_penalty - exploration_bonus

    return score


def pick_best_backend(route_id: int, backends: list):
    if not backends:
        return None

    best_backend = None
    best_score   = float("inf")

    for backend in backends:
        backend_id = backend["id"]
        score = get_backend_score(route_id, backend_id)

        # Tiny jitter breaks exact ties (e.g. two brand-new backends both
        # score -EXPLORE) without meaningfully changing real score ordering.
        score += random.uniform(0.0, 1e-4)

        if score < best_score:
            best_score   = score
            best_backend = backend

    return best_backend