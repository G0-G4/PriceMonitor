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
