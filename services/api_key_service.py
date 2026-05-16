from core.repository import (
    create_api_key_repo,
    get_api_keys_repo,
    delete_api_key_repo,
    get_project_owner,
    get_key_project,
    count_api_keys
)
from services.rate_limit_service import set_global_rate_limit_service


MAX_KEYS_PER_PROJECT = 5

DEFAULT_CAPACITY = 100
DEFAULT_REFILL = 10.0


async def create_api_key_service(user, project_id, name):

    if user is None:
        raise Exception("Not authenticated")

    owner = await get_project_owner(project_id)

    if not owner or owner["user_id"] != user["id"]:
        raise Exception("Not allowed")

    count = await count_api_keys(project_id)

    if count >= MAX_KEYS_PER_PROJECT:
        raise Exception("API key limit reached")

    key = await create_api_key_repo(project_id, name)

    await set_global_rate_limit_service(
        user,
        key["id"],
        {
            "capacity": DEFAULT_CAPACITY,
            "refill_rate": DEFAULT_REFILL
        }
    )

    return key


async def get_api_keys_service(user, project_id):

    if user is None:
        raise Exception("Not authenticated")

    owner = await get_project_owner(project_id)

    if not owner or owner["user_id"] != user["id"]:
        raise Exception("Not allowed")

    return await get_api_keys_repo(project_id)


async def delete_api_key_service(user, key_id):

    if user is None:
        raise Exception("Not authenticated")

    # get project of key
    row = await get_key_project(key_id)

    if not row:
        raise Exception("Key not found")

    project_id = row["tenant_id"]

    owner = await get_project_owner(project_id)

    if not owner or owner["user_id"] != user["id"]:
        raise Exception("Not allowed")

    await delete_api_key_repo(key_id)