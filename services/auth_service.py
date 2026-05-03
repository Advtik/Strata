from db.connect import db

async def get_or_create_user(github_id, username, avatar):
    async with db.pool.acquire() as conn:
        # check if user exists
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE github_id = $1",
            github_id
        )

        if row:
            return row

        # create new user
        row = await conn.fetchrow(
            """
            INSERT INTO users (github_id, username, avatar_url)
            VALUES ($1, $2, $3)
            RETURNING *
            """,
            github_id, username, avatar
        )

        return row