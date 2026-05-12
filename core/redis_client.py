from redis.asyncio import Redis
import os
from dotenv import load_dotenv

load_dotenv()

r = Redis.from_url(
    os.getenv("REDIS_URL"),
    decode_responses=True
)