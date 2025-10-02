import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///PriceMonitor.sqlite")

# Create async engine
engine = create_async_engine(DATABASE_URL, echo=False)

# Create async session factory
session_maker = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)
