from fastapi import Request, HTTPException
from services.api_key_service import (
    create_api_key_service,
    get_api_keys_service,
    delete_api_key_service
)


async def create_api_key_controller(request: Request, project_id: int):
    user = request.state.user

    if not user:
        raise HTTPException(401, "Not authenticated")

    try:
        key = await create_api_key_service(user,project_id)

        return {
            "id": key["id"],
            "key": key["key"]   # show only once in real product
        }

    except Exception as e:
        raise HTTPException(400, str(e))


async def get_api_keys_controller(request: Request, project_id: int):
    user = request.state.user

    if not user:
        raise HTTPException(401, "Not authenticated")

    try:
        keys = await get_api_keys_service(user,project_id)

        return [
            {"id": k["id"], "key": k["key"]}
            for k in keys
        ]

    except Exception as e:
        raise HTTPException(400, str(e))


async def delete_api_key_controller(request: Request, key_id: int):
    user = request.state.user

    if not user:
        raise HTTPException(401, "Not authenticated")

    try:
        await delete_api_key_service(user,key_id)

        return {"message": "Deleted"}

    except Exception as e:
        raise HTTPException(400, str(e))