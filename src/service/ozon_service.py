import asyncio
from datetime import datetime, date, timedelta
import pandas as pd

from src.api.ozon_api import OzonApi
from src.dto.item_dto import Item
from src.dto.price_change import PriceChangeResponse
from src.dto.price_dto import Price

from src.models.database import session_maker
from src.models.ozon_price import OzonPrice
from src.persistence.ozon_price_db import count_ozon_price_change, get_ozon_price_change, save_ozon_prices
from src.persistence.parameters_db import get_report_path
import os
import logging

logger = logging.getLogger(__name__)

class OzonService:
    def __init__(self, api: OzonApi):
        self.api = api

    async def get_ozon_prices(self, today: date, company_id: str):
        try:
            limit = 50
            offset = 0
            has_next = True
            page = 1
            await self.api.open_browser()
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
        finally:
            await self.api.close_browser()


    async def get_price_change(self, target_date: date, limit: int = 50, offset: int = 0, company_id: str|None = None, offer_id: str|None = None) -> PriceChangeResponse:
        async with session_maker() as session, session.begin():
            ozon_prices = await get_ozon_price_change(session, target_date, limit, offset, company_id, offer_id)
            total = await count_ozon_price_change(session, target_date, company_id, offer_id)
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
                name=item.part_item.name,
                date=today,
                marketing_seller_price=price.marketing_seller_price,
                old_price=price.old_price,
                marketing_price=price.marketing_price,
                marketing_oa_price=price.marketing_oa_price
            ))
        await save_ozon_prices(ozon_prices)

    async def prepare_excel_report(self, target_date: date, company_id: str|None = None, offer_id: str|None = None):
        report_date = target_date.strftime("%Y-%m-%d")
        report_date_time = datetime.now().strftime("%Y-%m-%d_%H-%m-%S")
        yesterday = (target_date - timedelta(days=1)).strftime("%Y-%m-%d")
        base_path = await get_report_path()
        if not base_path:
            base_path = './'
        else:
            base_path = base_path.value

        filename = os.path.join(base_path, f"price_changes_report_{report_date_time}_{company_id}.xlsx")
        
        # First check if there's any data
        response = await self.get_price_change(
            target_date=target_date,
            limit=1,
            offset=0,
            company_id=company_id,
            offer_id=offer_id
        )
        
        if not response.price_changes:
            logger.warning(f"No price changes found for {report_date} and company {company_id}")
            return None
            
        limit = 50
        offset = 0
        first_page = True
        
        with pd.ExcelWriter(filename, engine='openpyxl') as writer:
            while True:
                # Get price changes page by page
                response = await self.get_price_change(
                    target_date=target_date,
                    limit=limit,
                    offset=offset,
                    company_id=company_id,
                    offer_id=offer_id
                )
                
                if not response.price_changes:
                    break  # No more data
                
                # Convert to DataFrame
                df = pd.DataFrame([price.model_dump() for price in response.price_changes])

                column_order = [
                    'date', 'company_id', 'offer_id', 'name',
                    'yesterday_seller_price',
                    'yesterday_spp',
                    'yesterday_ozon_card',
                    'today_seller_price',
                    'today_spp',
                    'today_ozon_card',
                ]

                # Reorder columns
                df = df[column_order]

                # Rename columns for clarity
                column_rename = {
                    'today_seller_price': 'Цена Продажи ' + report_date,
                    'today_spp': 'СПП ' + report_date,
                    'today_ozon_card': 'Карта Озон ' + report_date,
                    'yesterday_seller_price': 'Цена Продажи ' + yesterday,
                    'yesterday_spp': 'СПП ' + yesterday,
                    'yesterday_ozon_card': 'Карта Озон ' + yesterday
                }
                df = df.rename(columns=column_rename)
                
                # Add empty column for formula
                df['Изменение Цены %'] = None
            
                # Write to Excel
                if first_page:
                    # Write header on first page
                    df.to_excel(writer, index=False, sheet_name='Price Changes')
                    # Add formula after writing
                    sheet = writer.sheets['Price Changes']
                    for row in range(2, len(df) + 2):
                        formula = f'=J{row}/G{row}'
                        sheet.cell(row=row, column=len(df.columns)).value = formula
                    first_page = False
                else:
                    # Append to existing sheet
                    startrow = writer.sheets['Price Changes'].max_row
                    df.to_excel(
                        writer,
                        index=False,
                        sheet_name='Price Changes',
                        startrow=startrow,
                        header=False
                    )
                    # Add formula for new rows
                    sheet = writer.sheets['Price Changes']
                    for row in range(startrow + 1, startrow + len(df) + 1):
                        formula = f'=J{row}/G{row}'
                        sheet.cell(row=row, column=len(df.columns)).value = formula

                offset += limit
                logger.info(f"written {offset} of {response.total} rows to excel")

                # Stop if we've processed all items
                if offset >= response.total:
                    break
        
        logger.info(f"Report saved as {filename}")
        return filename


async def main():
    ...
    # sender = await BrowserRequestSender("https://seller.ozon.ru/app/reviews").init()
    # api = OzonApi(sender)
    # service = OzonService(api)
    # await service.get_today_prices("836045")
    # await service.prepare_excel_report(datetime.now().date(),'1104328')

if __name__ == '__main__':
    asyncio.run(main())
