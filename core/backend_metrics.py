import random


backend_metrics = {}

def init_backend(route_name, backend_url):
    if route_name not in backend_metrics:
        backend_metrics[route_name] = {}

    if backend_url not in backend_metrics[route_name]:
        backend_metrics[route_name][backend_url] = {
            "requests": 0,
            "successes": 0,
            "failures": 0,
            "avg_latency": None,
            "recent_requests": 0
        }

def record_backend_success(route_name, backend_url, latency):
    init_backend(route_name, backend_url)

    m = backend_metrics[route_name][backend_url]

    m["requests"] += 1
    m["successes"] += 1
    m["recent_requests"]+=1
    ALPHA = 0.2
    if m["avg_latency"] is None:
        m["avg_latency"] = latency
    else:
        m["avg_latency"] = (1 - ALPHA) * m["avg_latency"] + ALPHA * latency



def record_backend_failure(route_name, backend_url):
    init_backend(route_name, backend_url)

    m = backend_metrics[route_name][backend_url]

    m["requests"] += 1
    m["failures"] += 1
    m["recent_requests"] += 1


def get_backend_score(route_name, backend_url):
    route_data = backend_metrics.get(route_name, {})
    m = route_data.get(backend_url)


    # no data → lowest priority
    if not m or m["requests"] == 0:
        return 0.5 + random.random()

    # backend with 0 success and a lot of failures was getting avg latency as 1 thats why 
    if m["successes"] == 0 and m["failures"] > 0:
        return float("inf")
    
    #decay load
    m["recent_requests"] *= 0.9

    # avg latency
    if m["successes"] > 0:
        avg_latency = m["avg_latency"] if m["avg_latency"] is not None else 1.0
    else:
        avg_latency = 1.0  # fallback (no success yet)


    # failure rate
    failure_rate = m["failures"] / m["requests"]

    load_penalty = m["recent_requests"] * 0.5

    # scoring formula
    penalty = 300  # tune later
    score = avg_latency + (failure_rate * penalty) + load_penalty

    if m["failures"] > 0:
        score += 100

    return score

def pick_best_backend(route_name, backends):
    best_backend = None
    best_score = float("inf")

    for backend in backends:
        url = backend["url"]
        score = get_backend_score(route_name, url)

        if score < best_score:
            best_score = score
            best_backend = backend

    return best_backend