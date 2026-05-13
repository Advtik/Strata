import time

from fastapi import Request


async def middleman(
    request: Request,
    call_next
):

    if (
        request.url.path.startswith("/auth")
        or request.url.path.startswith("/api")
        or request.url.path.startswith("/health")
    ):

        return await call_next(request)

    start_time = time.perf_counter()

    try:

        response = await call_next(request)

    except Exception as e:

        latency = (
            time.perf_counter() -
            start_time
        ) * 1000

        print(
            f"{request.method} "
            f"{request.url.path} "
            f"500 "
            f"{latency:.2f}ms"
        )

        raise e

    latency = (
        time.perf_counter() -
        start_time
    ) * 1000

    # optional lightweight log
    print(
        f"{request.method} "
        f"{request.url.path} "
        f"{response.status_code} "
        f"{latency:.2f}ms"
    )

    return response