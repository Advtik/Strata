from fastapi import Request, HTTPException
from services.api_key_service import (
    create_api_key_service,
    get_api_keys_service,
    delete_api_key_service
)
import traceback

async def create_api_key_controller(request: Request, project_id: int):
    user = request.state.user

    if not user:
        raise HTTPException(401, "Not authenticated")

    try:

        data = await request.json()

        name = data.get("name")

        key = await create_api_key_service(user,project_id, name)

        return {
            "id": key["id"],
            "key": key["key"] ,
            "name": key["name"]
              # show only once in real product
        }

    except Exception as e:
        traceback.print_exc()

        raise HTTPException(400, str(e))


async def get_api_keys_controller(request: Request, project_id: int):
    user = request.state.user

    if not user:
        raise HTTPException(401, "Not authenticated")

    try:
        keys = await get_api_keys_service(user,project_id)

        return [
            {
                "id": k["id"],
                "name": k["name"],
                "key_preview": k["key"][:16] + "...",
                "created_at": str(k["created_at"]),
                "refill_rate": k["refill_rate"] or 0,
                "capacity": k["capacity"] or 0
            }
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