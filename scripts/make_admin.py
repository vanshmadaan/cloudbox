import asyncio
import os
import sys
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.models.user import User


async def promote_user(email: str, db_url: str):
    clean_display = db_url.split('@')[-1] if '@' in db_url else db_url
    print(f"Connecting to database: {clean_display}...")
    engine = create_async_engine(db_url, echo=False)
    async with engine.begin() as conn:
        res = await conn.execute(select(User.id, User.email, User.is_superuser).where(User.email == email))
        user = res.first()
        if not user:
            print(f"❌ User '{email}' not found in database.")
            return

        if user.is_superuser:
            print(f"ℹ️ User '{email}' is ALREADY an administrator.")
            return

        await conn.execute(update(User).where(User.email == email).values(is_superuser=True))
        print(f"👑 Successfully promoted '{email}' to Superuser / Administrator!")
    await engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python scripts/make_admin.py '<USER_EMAIL>' '<DATABASE_URL>'")
        print("Example: python scripts/make_admin.py 'admin@example.com' 'postgresql+asyncpg://...'")
        sys.exit(1)

    target_email = sys.argv[1].strip()
    database_url = sys.argv[2].strip()
    asyncio.run(promote_user(target_email, database_url))
