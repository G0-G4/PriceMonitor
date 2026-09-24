import asyncio
import re
from dataclasses import dataclass

from src.models.database import session_maker
from src.models.parameters import Parameter
from sqlalchemy import select, delete


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


async def get_report_path() -> Parameter | None:
    async with session_maker() as session:
        return await find_parameter_by_name("report_path", session)

async def save_report_path(report_path: str):
    await save_parameter(Parameter(name="report_path", value=report_path))

async def find_parameter_by_name(name: str, session) -> Parameter | None:
    res = await session.execute(
        select(Parameter).where(
            Parameter.name == name,
            )
    )
    return res.scalar_one_or_none()

async def save_parameter(parameter: Parameter) -> Parameter | None:
    async with session_maker() as session, session.begin():
        existing = await find_parameter_by_name(parameter.name, session)
        if not existing:
            session.add(parameter)
            return parameter
        else:
            existing.value = parameter.value
            session.add(existing)
        return existing

async def get_scheduled_times() -> list[str]:
    async with session_maker() as session:
        query = select(Parameter).where(Parameter.name=='scheduled_time').order_by(Parameter.parameter_id)
        res = await session.execute(query)
        return [p.value for p in res.scalars().all()]

async def add_scheduled_time(scheduled_times: list[str]):
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


WB_API_TOKEN_NAME = "wb_api_token"
WB_ACCOUNT_NAME = "wb_account"
WB_TOKEN_PREFIX = "wb_token:"
_WB_ACCOUNT_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@dataclass
class WbAccount:
    name: str
    token: str | None


def normalize_wb_account(account: str) -> str:
    name = (account or "").strip()
    if not _WB_ACCOUNT_RE.fullmatch(name):
        raise ValueError("Account name may contain letters, digits, '.', '_' and '-' (1-64 chars)")
    return name


def _wb_token_param_name(account: str) -> str:
    return f"{WB_TOKEN_PREFIX}{account}"


async def migrate_legacy_wb_token():
    async with session_maker() as session, session.begin():
        legacy = await find_parameter_by_name(WB_API_TOKEN_NAME, session)
        if not legacy or not (legacy.value or "").strip():
            return
        existing = await session.execute(
            select(Parameter).where(Parameter.name == WB_ACCOUNT_NAME)
        )
        if existing.scalars().first() is None:
            session.add(Parameter(name=WB_ACCOUNT_NAME, value="wb"))
            session.add(Parameter(name=_wb_token_param_name("wb"), value=legacy.value.strip()))
        await session.delete(legacy)


async def get_wb_accounts() -> list[WbAccount]:
    await migrate_legacy_wb_token()
    async with session_maker() as session:
        names_res = await session.execute(
            select(Parameter).where(Parameter.name == WB_ACCOUNT_NAME).order_by(Parameter.parameter_id)
        )
        names = [p.value for p in names_res.scalars().all() if p.value]
        token_res = await session.execute(
            select(Parameter).where(Parameter.name.startswith(WB_TOKEN_PREFIX))
        )
        tokens = {
            p.name[len(WB_TOKEN_PREFIX):]: (p.value.strip() if p.value else None)
            for p in token_res.scalars().all()
        }
        return [WbAccount(name=name, token=tokens.get(name)) for name in names]


async def get_wb_account_names() -> list[str]:
    return [account.name for account in await get_wb_accounts()]


async def get_wb_api_token(account: str | None = None) -> str | None:
    if account:
        async with session_maker() as session:
            parameter = await find_parameter_by_name(_wb_token_param_name(account), session)
            if parameter and parameter.value:
                return parameter.value.strip()
            return None
    accounts = await get_wb_accounts()
    for item in accounts:
        if item.token:
            return item.token
    return None


async def add_wb_account(account: str, token: str):
    account = normalize_wb_account(account)
    token = token.strip()
    if not token:
        raise ValueError("Token is empty")
    async with session_maker() as session, session.begin():
        existing = await session.execute(
            select(Parameter).where(
                Parameter.name == WB_ACCOUNT_NAME,
                Parameter.value == account,
            )
        )
        if existing.scalar_one_or_none() is None:
            session.add(Parameter(name=WB_ACCOUNT_NAME, value=account))
        token_param = await find_parameter_by_name(_wb_token_param_name(account), session)
        if token_param is None:
            session.add(Parameter(name=_wb_token_param_name(account), value=token))
        else:
            token_param.value = token


async def delete_wb_account(account: str):
    account = normalize_wb_account(account)
    async with session_maker() as session, session.begin():
        await session.execute(
            delete(Parameter).where(
                Parameter.name == WB_ACCOUNT_NAME,
                Parameter.value == account,
            )
        )
        token_param = await find_parameter_by_name(_wb_token_param_name(account), session)
        if token_param:
            await session.delete(token_param)


def mask_token(token: str | None) -> str:
    if not token:
        return ""
    if len(token) <= 8:
        return "••••"
    return token[:4] + "…" + token[-4:]




async def main():
    await save_parameter(Parameter(name="p", value="2"))

if __name__ == '__main__':
    asyncio.run(main())