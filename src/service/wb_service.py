from datetime import datetime, date, timedelta
import logging
import os

import pandas as pd

from src.api.wb_api import WbApi
from src.browser_request_sender import profile_exists
from src.config import WB_USER_DATA_DIR
from src.dto.wb_price_dto import WbPriceChangeResponse
from src.models.database import session_maker
from src.models.wb_price import WbPrice
from src.persistence.parameters_db import get_report_path, get_wb_api_token
from src.persistence.wb_price_db import (
    count_wb_price_change,
    get_previous_wb_day,
    get_wb_price_change,
    save_wb_prices,
)

logger = logging.getLogger(__name__)

WB_ACCOUNT = "wb"


class WbService:
    def __init__(self, api: WbApi):
        self.api = api

    async def collect_prices(self, today: date):
        token = await get_wb_api_token()
        if not token:
            raise Exception("WB API token is not configured")
        if not profile_exists(WB_USER_DATA_DIR):
            raise Exception("WB seller login required")

        goods = await self.api.get_prices(token)
        names = await self.api.get_card_names(token)

        await self.api.open_browser()
        try:
            discounts = await self.api.get_discount_on_site()
        finally:
            await self.api.close_browser()

        discount_by_nm = {}
        for item in discounts:
            nm_id = item.resolved_nm_id()
            if nm_id is None:
                continue
            discount_by_nm[nm_id] = item.discountOnSite if item.discountOnSite is not None else 0
        prices: list[WbPrice] = []
        for item in goods:
            wb_discount = discount_by_nm.get(item.nmID, 0) if item.nmID is not None else 0
            name = names.get(item.nmID) or item.vendorCode
            for size in item.sizes or []:
                prices.append(WbPrice(
                    account=WB_ACCOUNT,
                    nm_id=item.nmID,
                    vendor_code=item.vendorCode,
                    size_id=size.sizeID,
                    tech_size_name=size.techSizeName,
                    name=name,
                    date=today,
                    price=size.price,
                    discounted_price=size.discountedPrice,
                    club_discounted_price=size.clubDiscountedPrice,
                    discount=item.discount or 0,
                    club_discount=item.clubDiscount or 0,
                    wb_discount=wb_discount,
                ))
        batch_size = 40
        for i in range(0, len(prices), batch_size):
            await save_wb_prices(prices[i:i + batch_size])
        logger.info("saved %s WB price rows", len(prices))

    async def get_price_change(
        self,
        target_date: date,
        previous_date: date,
        limit: int = 50,
        offset: int = 0,
        vendor_code: str | None = None,
    ) -> WbPriceChangeResponse:
        async with session_maker() as session, session.begin():
            changes = await get_wb_price_change(
                session, target_date, previous_date, limit, offset, vendor_code
            )
            total = await count_wb_price_change(session, target_date, vendor_code)
            return WbPriceChangeResponse(price_changes=changes, total=total)

    async def prepare_excel_report(self, target_date: date, vendor_code: str | None = None):
        report_date = target_date.strftime("%Y-%m-%d")
        report_date_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        previous_date = (await get_previous_wb_day(target_date)) or (target_date - timedelta(days=1))
        base_path = await get_report_path()
        base_path = base_path.value if base_path else "./"
        filename = os.path.join(base_path, f"wb_price_changes_report_{report_date_time}.xlsx")

        response = await self.get_price_change(
            target_date=target_date,
            previous_date=previous_date,
            limit=1,
            offset=0,
            vendor_code=vendor_code,
        )
        if not response.price_changes:
            logger.warning("No WB price changes found for %s", report_date)
            return None

        limit = 50
        offset = 0
        first_page = True
        previous_label = previous_date.strftime("%Y-%m-%d")

        with pd.ExcelWriter(filename, engine="openpyxl") as writer:
            while True:
                response = await self.get_price_change(
                    target_date=target_date,
                    previous_date=previous_date,
                    limit=limit,
                    offset=offset,
                    vendor_code=vendor_code,
                )
                if not response.price_changes:
                    break

                df = pd.DataFrame([price.model_dump() for price in response.price_changes])
                column_order = [
                    "vendor_code",
                    "name",
                    "tech_size_name",
                    "yesterday_seller_price",
                    "yesterday_spp",
                    "yesterday_club",
                    "today_seller_price",
                    "today_spp",
                    "today_club",
                ]
                df = df[column_order]
                df = df.rename(columns={
                    "vendor_code": "vendor_code",
                    "name": "name",
                    "tech_size_name": "size",
                    "today_seller_price": "Цена Продажи " + report_date,
                    "today_spp": "СПП " + report_date,
                    "today_club": "WB Клуб " + report_date,
                    "yesterday_seller_price": "Цена Продажи " + previous_label,
                    "yesterday_spp": "СПП " + previous_label,
                    "yesterday_club": "WB Клуб " + previous_label,
                })
                df["Изменение Цены %"] = None

                if first_page:
                    df.to_excel(writer, index=False, sheet_name="Price Changes")
                    sheet = writer.sheets["Price Changes"]
                    for row in range(2, len(df) + 2):
                        sheet.cell(row=row, column=len(df.columns)).value = f"=H{row}/E{row}"
                    first_page = False
                else:
                    startrow = writer.sheets["Price Changes"].max_row
                    df.to_excel(
                        writer,
                        index=False,
                        sheet_name="Price Changes",
                        startrow=startrow,
                        header=False,
                    )
                    sheet = writer.sheets["Price Changes"]
                    for row in range(startrow + 1, startrow + len(df) + 1):
                        sheet.cell(row=row, column=len(df.columns)).value = f"=H{row}/E{row}"

                offset += limit
                logger.info("written %s of %s WB rows to excel", offset, response.total)
                if offset >= response.total:
                    break

        logger.info("WB report saved as %s", filename)
        return filename
