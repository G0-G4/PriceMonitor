from models.database import session_maker
from models.ozon_price import OzonPrice
import logging

logger = logging.getLogger(__name__)

async def save_ozon_prices(prices: list[OzonPrice]):
    count = 0
    async with session_maker() as session, session.begin():
        for price in prices:
            session.add(price)
            count += 1
    logger.info(f"persisted {count} prices")