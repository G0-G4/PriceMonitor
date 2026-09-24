import logging
from datetime import date

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import aliased

from src.dto.wb_price_dto import WbPriceChange
from src.models.database import session_maker
from src.models.wb_price import WbPrice

logger = logging.getLogger(__name__)


def _buyer_price(discounted_price, wb_discount):
    if discounted_price is None:
        return None
    discount = wb_discount or 0
    return discounted_price * (1 - discount / 100.0)


async def save_wb_prices(prices: list[WbPrice]):
    if not prices:
        logger.info("No WB prices to save")
        return

    async with session_maker() as session:
        values = [{
            "account": price.account,
            "nm_id": price.nm_id,
            "vendor_code": price.vendor_code,
            "size_id": price.size_id,
            "tech_size_name": price.tech_size_name,
            "name": price.name,
            "date": price.date,
            "price": price.price,
            "discounted_price": price.discounted_price,
            "club_discounted_price": price.club_discounted_price,
            "discount": price.discount,
            "club_discount": price.club_discount,
            "wb_discount": price.wb_discount,
        } for price in prices]

        stmt = insert(WbPrice).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["account", "nm_id", "size_id", "date"],
            set_={
                "vendor_code": stmt.excluded.vendor_code,
                "tech_size_name": stmt.excluded.tech_size_name,
                "name": stmt.excluded.name,
                "price": stmt.excluded.price,
                "discounted_price": stmt.excluded.discounted_price,
                "club_discounted_price": stmt.excluded.club_discounted_price,
                "discount": stmt.excluded.discount,
                "club_discount": stmt.excluded.club_discount,
                "wb_discount": stmt.excluded.wb_discount,
            }
        )
        await session.execute(stmt)
        await session.commit()
    logger.info("Bulk upserted %s WB prices", len(prices))


async def get_wb_price_change(
    session,
    target_date: date,
    previous_date: date,
    limit: int = 50,
    offset: int = 0,
    vendor_code: str | None = None,
    account: str | None = None,
) -> list[WbPriceChange]:
    Yesterday = aliased(WbPrice)
    query = select(WbPrice, Yesterday).select_from(WbPrice).outerjoin(
        Yesterday,
        and_(
            WbPrice.account == Yesterday.account,
            WbPrice.nm_id == Yesterday.nm_id,
            WbPrice.size_id == Yesterday.size_id,
            Yesterday.date == previous_date,
        )
    ).where(
        WbPrice.date == target_date
    )
    if vendor_code:
        query = query.where(WbPrice.vendor_code == vendor_code)
    if account:
        query = query.where(WbPrice.account == account)
    query = query.order_by(WbPrice.account, WbPrice.vendor_code, WbPrice.size_id).limit(limit).offset(offset)

    result = await session.execute(query)
    rows = result.all()
    changes = []
    for today, yesterday in rows:
        changes.append(WbPriceChange(
            date=target_date,
            account=today.account,
            nm_id=today.nm_id,
            vendor_code=today.vendor_code,
            name=today.name,
            tech_size_name=today.tech_size_name,
            today_seller_price=today.discounted_price,
            today_spp=_buyer_price(today.discounted_price, today.wb_discount),
            today_club=today.club_discounted_price,
            yesterday_seller_price=yesterday.discounted_price if yesterday else None,
            yesterday_spp=_buyer_price(yesterday.discounted_price, yesterday.wb_discount) if yesterday else None,
            yesterday_club=yesterday.club_discounted_price if yesterday else None,
        ))
    return changes


async def count_wb_price_change(
    session,
    target_date: date,
    vendor_code: str | None = None,
    account: str | None = None,
) -> int:
    query = select(func.count()).select_from(WbPrice).where(WbPrice.date == target_date)
    if vendor_code:
        query = query.where(WbPrice.vendor_code == vendor_code)
    if account:
        query = query.where(WbPrice.account == account)
    result = await session.execute(query)
    return result.scalar_one()


async def get_previous_wb_day(today: date, account: str | None = None):
    async with session_maker() as session:
        query = select(WbPrice.date).where(WbPrice.date < today)
        if account:
            query = query.where(WbPrice.account == account)
        result = await session.execute(
            query.order_by(WbPrice.date.desc()).limit(1)
        )
        return result.scalar_one_or_none()
