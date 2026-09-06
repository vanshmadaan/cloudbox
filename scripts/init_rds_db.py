import asyncio
import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import create_async_engine

from app.db.base import Base
from app.models.user import User
from app.models.blob import ContentBlob
from app.models.folder import Folder
from app.models.file import File
from app.models.share import SharedLink
async def init_db(db_url: str):
    clean_display = db_url.split('@')[-1] if '@' in db_url else db_url
    print(f"Connecting to RDS: {clean_display}...")
    engine = create_async_engine(db_url, echo=False)
    async with engine.begin() as conn:
        print("Creating all tables in RDS PostgreSQL...")
        await conn.run_sync(Base.metadata.create_all)
        print("✅ Tables created successfully:")
        for table in Base.metadata.tables.keys():
            print(f"  - {table}")
    await engine.dispose()
    print("✅ Database ready for production!")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/init_rds_db.py '<DATABASE_URL>'")
        sys.exit(1)
    asyncio.run(init_db(sys.argv[1]))
