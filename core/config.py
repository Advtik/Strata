routes={
    "echo":"http://postman-echo.com",
    "json":"http://jsonplaceholder.typicode.com"
}

tenants={
    "key1":{
        "name":"user1",
        "routes":["echo"]
    },
    "key2":{
        "name":"user2",
        "routes":["json","echo"]
    }
}


# ---------------- CONFIG ----------------
rate_limit_config = {
    "key1": {
        "refill_rate": 1,   # tokens per second
        "capacity": 10
    },
    "key2": {
        "refill_rate": 1,
        "capacity": 10
    }
}