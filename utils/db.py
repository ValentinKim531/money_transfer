from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)
from .config import settings

engine = create_async_engine(settings.db_url, echo=False, future=True)
SessionLocal = async_sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession
)


async def get_db():
    async with SessionLocal() as session:
        yield session
