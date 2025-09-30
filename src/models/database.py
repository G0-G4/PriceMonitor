import os
import re
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# Database configuration
DATABASE_URL = "sqlite+aiosqlite:///./PriceMonitor.sqlite"

# Create async engine
engine = create_async_engine(DATABASE_URL, echo=False)

# Create async session factory
session_maker = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def run_migration(conn, filename: str, migration_dir: str):
    """Run a single migration file"""
    with open(os.path.join(migration_dir, filename)) as f:
        sql = f.read()
    
    # Execute each statement separately
    for statement in sql.split(';'):
        if statement.strip():
            await conn.execute(text(statement))
    
    # Record migration
    await conn.execute(
        text("INSERT INTO migrations (filename, applied_at) VALUES (:filename, :applied_at)"),
        {"filename": filename, "applied_at": datetime.now().isoformat()}
    )
    print(f"✅ Applied migration: {filename}")

async def setup_migrations():
    """Setup database by running all pending migrations"""
    migration_dir = "migrations"
    if not os.path.exists(migration_dir):
        return
        
    async with engine.begin() as conn:
        # Get or create migrations table
        try:
            await conn.execute(text("SELECT 1 FROM migrations LIMIT 1"))
        except:
            await run_migration(conn, "004_migration_tracker.sql", migration_dir)
        
        # Get applied migrations
        result = await conn.execute(text("SELECT filename FROM migrations"))
        applied = {row[0] for row in result}
        
        # Find and sort migration files
        migrations = []
        for f in os.listdir(migration_dir):
            if match := re.match(r'^(\d+)_.+\.sql$', f):
                migrations.append((int(match.group(1)), f))
        
        # Run migrations in order
        for num, filename in sorted(migrations, key=lambda x: x[0]):
            if filename not in applied:
                try:
                    await run_migration(conn, filename, migration_dir)
                except Exception as e:
                    print(f"❌ Failed to apply {filename}: {str(e)}")
                    raise
