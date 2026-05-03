from fastapi import APIRouter
import httpx
from jose import jwt
from services.auth_service import get_or_create_user
from fastapi import Request
import os
from controllers.user_auth_controller import github_login_controller,github_callback_controller

router = APIRouter()

GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")

GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
JWT_SECRET = os.getenv("JWT_SECRET")

@router.get("/github/login")
def github_login():
    return github_login_controller()



@router.get("/github/callback")
async def github_callback(code: str):
    return await github_callback_controller(code)


@router.get("/me")
async def get_me(request: Request):

    if request.state.user is None:
        return {"error": "Not authenticated"}

    user = request.state.user

    return {
        "id": user["id"],
        "username": user["username"],
        "avatar": user["avatar_url"]
    }