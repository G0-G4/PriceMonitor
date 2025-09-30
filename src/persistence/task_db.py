import asyncio
from sqlalchemy import select, func
from src.models.task import Task
from src.models.database import session_maker
import logging

logger = logging.getLogger(__name__)

async def save_task(task: Task):
    async with session_maker() as session, session.begin():
        session.add(task)

async def get_tasks(session, limit: int = 50, offset: int = 0):
    result = await session.execute(
        select(Task)
        .order_by(Task.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return result.scalars().all()

async def count_tasks(session):
    result = await session.execute(select(func.count(Task.task_id)))
    return result.scalar()

async def main():
    task = Task(status = "NEW TASK")
    await save_task(task)
    await asyncio.sleep(10)
    task.status = "ANOTHER"
    await save_task(task)

if __name__ == '__main__':
    asyncio.run(main())
