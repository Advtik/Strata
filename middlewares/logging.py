import time
from fastapi import Request



async def middleman(request:Request, call_next):
    start_time = time.perf_counter()
    # print((request.headers))
    try:
        response = await call_next(request)
    except Exception as e:
        time_duration = time.perf_counter() - start_time
        print(request.method, request.url.path, 500, time_duration)
        raise e

    time_duration = (time.perf_counter() - start_time)*1000  #in ms
    print({
        "method":request.method, 
        "url_path":request.url.path, 
        "status_code":response.status_code,
        "latency":time_duration
    })
    return response
