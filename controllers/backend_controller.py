from fastapi import Request, HTTPException

import traceback
from services.backend_service import (
    create_backend_service,
    get_backends_service,
    delete_backend_service
)


async def create_backend_controller(request: Request, route_id: int):
    user = request.state.user

    try:
        data = await request.json()

        backend = await create_backend_service(user, route_id, data)

        return {
            "id": backend["id"],
            "url": backend["url"]
        }

    except Exception as e:

        traceback.print_exc()

        raise HTTPException(400, str(e))


async def get_backends_controller(request: Request, route_id: int):
    user = request.state.user

    try:
        backends = await get_backends_service(user, route_id)

        return [
            {
                "id": b["id"],
                "url": b["url"]
            }
            for b in backends
        ]

    except Exception as e:
        raise HTTPException(400, str(e))


async def delete_backend_controller(request: Request, backend_id: int):
    user = request.state.user

    try:
        await delete_backend_service(user, backend_id)

        return {"message": "Backend deleted"}

    except Exception as e:
        raise HTTPException(400, str(e))