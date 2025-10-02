import asyncio

from models.database import session_maker
from models.parameters import Parameter
from sqlalchemy import exists, select

async def add_company_ids(company_ids: list[str]):
    company_ids = [c_id.strip() for c_id in company_ids]
    async with session_maker() as session, session.begin():
        for company_id in company_ids:
            existing = await find_company_id(session, company_id)
            if not existing:
                session.add(Parameter(
                    name='company_id',
                    value=company_id
                ))

async def get_company_ids() -> list[str]:
    async with session_maker() as session:
        query = select(Parameter).where(Parameter.name=='company_id').order_by(Parameter.parameter_id)
        res = await session.execute(query)
        return [p.value for p in res.scalars().all()]

async def delete_company_id(company_id: str):
    async with session_maker() as session, session.begin():
        company_id = await find_company_id(session, company_id)
        if company_id:
            await session.delete(company_id)


async def find_company_id(session, company_id: str) -> Parameter | None:
        res = await session.execute(
            select(Parameter).where(
                Parameter.name == 'company_id',
                Parameter.value == company_id
            )
        )
        return res.scalar_one_or_none()

async def upsert_cookies(cookies_str:str):
    async with session_maker() as session, session.begin():
        cookies = await _get_cookies(session)
        if not cookies:
            new_cookies = Parameter(name="cookies", value=cookies_str)
            session.add(new_cookies)
        else:
            cookies.value = cookies_str

async def _get_cookies(session) -> Parameter | None:
    res = await session.execute(
        select(Parameter).where(
            Parameter.name == 'cookies',
        )
    )
    return res.scalar_one_or_none()

async def get_cookies() -> Parameter | None:
    async with session_maker() as session:
        return await _get_cookies(session)

async def get_scheduled_times() -> list[str]:
    async with session_maker() as session:
        query = select(Parameter).where(Parameter.name=='scheduled_time').order_by(Parameter.parameter_id)
        res = await session.execute(query)
        return [p.value for p in res.scalars().all()]

async def add_scheduled_time(scheduled_times: list[str]) -> list[str]:
    async with session_maker() as session, session.begin():
        for scheduled_time in scheduled_times:
            existing = await find_scheduled_time(session, scheduled_time)
            if not existing:
                session.add(Parameter(
                    name='scheduled_time',
                    value=scheduled_time
                ))

async def find_scheduled_time(session, scheduled_time: str) -> Parameter | None:
    res = await session.execute(
        select(Parameter).where(
            Parameter.name == 'scheduled_time',
            Parameter.value == scheduled_time
        )
    )
    return res.scalar_one_or_none()

async def delete_scheduled_time(scheduled_time: str):
    async with session_maker() as session, session.begin():
        scheduled_time = await find_scheduled_time(session, scheduled_time)
        if scheduled_time:
            await session.delete(scheduled_time)




async def main():
    await upsert_cookies('222')

if __name__ == '__main__':
    asyncio.run(main())