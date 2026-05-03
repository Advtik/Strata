from fastapi import Request
from jose import jwt, JWTError
from db.connect import db
import os

JWT_SECRET = os.getenv("JWT_SECRET")


async def user_middleware(request: Request, call_next):

    auth_header = request.headers.get("Authorization")

    if auth_header is None:
        request.state.user = None
        return await call_next(request)

    try:
        # Extract token
        token = auth_header.split(" ")[1]

        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])

        user_id = payload.get("user_id")

        async with db.pool.acquire() as conn:
            user = await conn.fetchrow(
                "SELECT * FROM users WHERE id = $1",
                user_id
            )

        request.state.user = user

    except JWTError:
        request.state.user = None

    response = await call_next(request)
    return response