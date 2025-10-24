import asyncio
import logging
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import and_, select, func
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import aliased

from src.dto.price_change import PriceChange
from src.models.database import session_maker
from src.models.ozon_price import OzonPrice

logger = logging.getLogger(__name__)

async def save_ozon_prices(prices: list[OzonPrice]):
    if not prices:
        logger.info("No prices to save")
        return
        
    async with session_maker() as session:
        values = [{
            'company_id': price.company_id,
            'item_id': price.item_id,
            'offer_id': price.offer_id,
            'name': price.name,
            'date': price.date,
            'marketing_seller_price': price.marketing_seller_price,
            'old_price': price.old_price,
            'marketing_price': price.marketing_price,
            'marketing_oa_price': price.marketing_oa_price
        } for price in prices]
        
        stmt = insert(OzonPrice).values(values)
        
        stmt = stmt.on_conflict_do_update(
            index_elements=['company_id', 'offer_id', 'date'],
            set_={
                'marketing_seller_price': stmt.excluded.marketing_seller_price,
                'old_price': stmt.excluded.old_price,
                'marketing_price': stmt.excluded.marketing_price,
                'marketing_oa_price': stmt.excluded.marketing_oa_price
            }
        )
        
        await session.execute(stmt)
        await session.commit()
        
    logger.info(f"Bulk upserted {len(prices)} prices")

async def get_ozon_price_change(
    session,
    target_date: date,
    limit: int = 50,
    offset: int = 0,
    company_id: str|None = None,
    offer_id: str|None = None
) -> list[PriceChange]:
    """
    Get paginated price changes for a specific date with optional company filter
    """
    OzonPriceYesterday = aliased(OzonPrice)
    query = select(
        OzonPrice.company_id,
        OzonPrice.offer_id,
        OzonPrice.name,
        OzonPrice.marketing_seller_price.label('today_seller_price'),
        OzonPrice.marketing_oa_price.label('today_ozon_card'),
        OzonPrice.marketing_price.label('today_spp'),
        OzonPriceYesterday.marketing_seller_price.label('yesterday_seller_price'),
        OzonPriceYesterday.marketing_oa_price.label('yesterday_ozon_card'),
        OzonPriceYesterday.marketing_price.label('yesterday_spp')
    ).select_from(
        OzonPrice
    ).outerjoin(
        OzonPriceYesterday,
        and_(
            OzonPrice.company_id == OzonPriceYesterday.company_id,
            OzonPrice.offer_id == OzonPriceYesterday.offer_id,
            OzonPriceYesterday.date == target_date - timedelta(days=1)
        )
    ).where(
        OzonPrice.date == target_date
    )

    if company_id:
        query = query.where(OzonPrice.company_id == company_id)
    if offer_id:
        query = query.where(OzonPrice.offer_id == offer_id)

    query = query.order_by(OzonPrice.item_id).limit(limit).offset(offset)

    result = await session.execute(query)
    rows = result.all()

    return [
        PriceChange(
            date=target_date,
            company_id=row.company_id,
            offer_id=row.offer_id,
            name=row.name,
            today_seller_price=row.today_seller_price,
            today_spp=row.today_spp,
            today_ozon_card=row.today_ozon_card,
            yesterday_seller_price=row.yesterday_seller_price,
            yesterday_spp=row.yesterday_spp,
            yesterday_ozon_card=row.yesterday_ozon_card
        )
        for row in rows
    ]

async def count_ozon_price_change(
    session,
    target_date: date,
    company_id: str|None = None,
    offer_id : str|None = None
) -> int:
    """
    Count total price changes for a specific date with optional company filter
    """
    OzonPriceYesterday = aliased(OzonPrice)
    query = select(
        func.count()
    ).select_from(
        OzonPrice
    ).outerjoin(
        OzonPriceYesterday,
        and_(
            OzonPrice.company_id == OzonPriceYesterday.company_id,
            OzonPrice.offer_id == OzonPriceYesterday.offer_id,
            OzonPriceYesterday.date == target_date - timedelta(days=1)
        )
    ).where(
        OzonPrice.date == target_date
    )

    if company_id:
        query = query.where(OzonPrice.company_id == company_id)
    if offer_id:
        query = query.where(OzonPrice.offer_id == offer_id)

    result = await session.execute(query)
    return result.scalar_one()
async def main():
    prices = await get_ozon_price_change(datetime.now(UTC).date())
    count = await count_ozon_price_change(datetime.now(UTC).date())
    print(prices)
    print(count)

if __name__ == "__main__":
    asyncio.run(main())
