import asyncio
from datetime import datetime, UTC, date

from api.ozon_api import OzonApi
from browser_request_sender import BrowserRequestSender
from dto.item_dto import Item
from dto.price_change import PriceChange, PriceChangeResponse
from dto.price_dto import Price
import logging.handlers
import sys

from models.database import session_maker
from models.ozon_price import OzonPrice
from persistence.ozon_price_db import count_ozon_price_change, get_ozon_price_change, save_ozon_prices

log_filename = f"test.log"

root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)

formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(filename)s - %(lineno)d - %(message)s')

# File handler
file_handler = logging.handlers.RotatingFileHandler(
    log_filename,
    backupCount=3,
    maxBytes=5_000_000
)
file_handler.setFormatter(formatter)

# Console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)

root_logger.handlers = []
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

logger = logging.getLogger(__name__)


class OzonService:
    def __init__(self, api: OzonApi):
        self.api = api

    async def get_today_prices(self, company_id: str):
        limit = 50
        offset = 0
        has_next = True
        page = 1
        today = datetime.now(UTC).date()
        while has_next:
            products_response = await self.api.list_by_filter(company_id, limit=limit, offset=offset)
            item_ids = [item.item_id for item in products_response.products]
            price_response = await self.api.get_common_prices(company_id, item_ids)

            await self.convert_and_save_ozon_prices(products_response.products, price_response.items, today)

            offset += len(products_response.products)
            has_next = len(products_response.products) > 0
            logger.info(f"loaded {len(products_response.products)} products on {page} page")
            page += 1
            await asyncio.sleep(0.5)

    async def get_price_change(self, target_date: date, limit: int = 50, offset: int = 0, company_id: str = None) -> PriceChangeResponse:
        async with session_maker() as session, session.begin():
            ozon_prices = await get_ozon_price_change(session, target_date, limit, offset, company_id)
            total = await count_ozon_price_change(session, target_date, company_id)
            return PriceChangeResponse(price_changes=ozon_prices, total=total)

    async def convert_and_save_ozon_prices(self, items: list[Item], prices: list[Price], today: date):
        price_map:dict[str, Price] = {price.item_id : price for price in prices}
        ozon_prices = []
        for item in items:
            if item.item_id not in price_map:
                logger.warning(f"price not found for {item}. it will not be saved")
            price = price_map.get(item.item_id)
            ozon_prices.append(OzonPrice(
                company_id=item.company_id,
                item_id=item.item_id,
                offer_id=item.part_item.offer_id,
                date=today,
                marketing_seller_price=price.marketing_seller_price,
                old_price=price.old_price,
                marketing_price=price.marketing_price,
                marketing_oa_price=price.marketing_oa_price
            ))
        await save_ozon_prices(ozon_prices)

    async def prepare_excel_report(self):
       ...


async def main():
    sender = await BrowserRequestSender("https://seller.ozon.ru/app/reviews").init()
    api = OzonApi(sender)
    service = OzonService(api)
    await service.get_today_prices("836045")

if __name__ == '__main__':
    asyncio.run(main())