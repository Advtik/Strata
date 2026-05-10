from fastapi import Request, HTTPException
import traceback
from services.route_service import (
    create_route_service,
    get_routes_service,
    delete_route_service,
    get_route_detail_service
)


async def create_route_controller(request: Request, project_id: int):
    user = request.state.user

    try:
        data = await request.json()

        route = await create_route_service(user, project_id, data)

        return {
            "id": route["id"],
            "name": route["name"]
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


async def get_routes_controller(request: Request, project_id: int):
    user = request.state.user

    try:
        routes = await get_routes_service(user, project_id)

        return routes

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    

async def delete_route_controller(request, route_id: int):
    user = request.state.user

    try:
        await delete_route_service(user, route_id)
        return {"message": "Route deleted"}

    except Exception as e:
        raise HTTPException(400, str(e))
    

async def get_route_detail_controller(
    request: Request,
    route_id: int
):

    user = request.state.user

    try:

        route = await get_route_detail_service(
            user,
            route_id
        )

        return route

    except Exception as e:

        traceback.print_exc()

        raise HTTPException(
            status_code=400,
            detail=str(e)
        )