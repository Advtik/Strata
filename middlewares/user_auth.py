from fastapi import Request
from jose import jwt, JWTError
from db.connect import db
import os


JWT_SECRET = os.getenv("JWT_SECRET")


async def user_middleware(request: Request, call_next):

    token = request.cookies.get("strata_token")
    print("TOKEN:", token)

    if token is None:
        request.state.user = None
        return await call_next(request)

    try:

        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        print("PAYLOAD:", payload)

        user_id = payload.get("user_id")

        async with db.pool.acquire() as conn:
            user = await conn.fetchrow(
                "SELECT * FROM users WHERE id = $1",
                user_id
            )

        request.state.user = user

    except JWTError as e:
        print("JWT ERROR:", e)
        request.state.user = None

    response = await call_next(request)
    return response