from sqlalchemy.dialects.sqlite import insert
from models.database import session_maker
from models.ozon_price import OzonPrice
import logging

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

from datetime import date, timedelta
from sqlalchemy import select, and_
from sqlalchemy.orm import aliased
from models.database import session_maker
from models.ozon_price import OzonPrice
from dto.price_change import PriceChange
import logging

logger = logging.getLogger(__name__)

async def get_ozon_price_change(
    target_date: date,
    limit: int = 50,
    offset: int = 0,
    company_id: str = None
) -> list[PriceChange]:
    """
    Get paginated price changes for a specific date with optional company filter
    
    Args:
        target_date: Date to get price changes for
        limit: Maximum number of results to return
        offset: Number of results to skip
        company_id: Optional company ID filter
    
    Returns:
        List of PriceChange objects showing price differences between target_date and previous day
    """
    async with session_maker() as session:
        # Create alias for yesterday's prices
        OzonPriceYesterday = aliased(OzonPrice)
        
        # Base query for today's prices with left join to yesterday's prices
        query = select(
            OzonPrice.company_id,
            OzonPrice.offer_id,
            OzonPrice.marketing_seller_price.label('today_seller_price'),
            OzonPrice.marketing_oa_price.label('today_spp'),
            OzonPrice.marketing_price.label('today_ozon_card'),
            OzonPriceYesterday.marketing_seller_price.label('yesterday_seller_price'),
            OzonPriceYesterday.marketing_oa_price.label('yesterday_spp'),
            OzonPriceYesterday.marketing_price.label('yesterday_ozon_card')
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
        ).limit(limit).offset(offset)
        
        if company_id:
            query = query.where(OzonPrice.company_id == company_id)
            
        result = await session.execute(query)
        rows = result.all()
        
        return [
            PriceChange(
                date=target_date,
                company_id=row.company_id,
                offer_id=row.offer_id,
                today_seller_price=row.today_seller_price or 0,
                today_spp=row.today_spp or 0,
                today_ozon_card=row.today_ozon_card or 0,
                yesterday_seller_price=row.yesterday_seller_price or 0,
                yesterday_spp=row.yesterday_spp or 0,
                yesterday_ozon_card=row.yesterday_ozon_card or 0
            )
            for row in rows
        ]
