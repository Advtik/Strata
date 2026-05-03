from fastapi import APIRouter
import httpx
from jose import jwt
from services.auth_service import get_or_create_user
from fastapi import Request
import os

GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")

GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
JWT_SECRET = os.getenv("JWT_SECRET")


def github_login_controller():
    return {
        "url": f"https://github.com/login/oauth/authorize?client_id={GITHUB_CLIENT_ID}"
    }


async def github_callback_controller(code: str):
    async with httpx.AsyncClient() as client:
        token_res = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code
            }
        )

        access_token = token_res.json().get("access_token")

        user_res = await client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {access_token}"}
        )

        user_data = user_res.json()

    user = await get_or_create_user(
        str(user_data["id"]),
        user_data["login"],
        user_data["avatar_url"]
    )

    token = jwt.encode(
        {"user_id": user["id"]},
        JWT_SECRET,
        algorithm="HS256"
    )

    return {"token": token}

