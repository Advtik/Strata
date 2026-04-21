routes={
    "echo": {
        "backends": [
            {"url":"http://postman-echos.com"},
            {"url":"https://httpbins.org"},
            {"url":"http://127.0.0.1:9000"}
        ]
    },
    "json":{
        "backends":[
            {"url":"http://jsonplaceholder.typicode.com"}
        ]
    }
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
        "capacity": 5
    }
}