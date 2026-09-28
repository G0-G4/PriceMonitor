from datetime import datetime, date, timedelta
import logging
import os

import pandas as pd

from src.api.wb_api import WbApi
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


def _wb_discount(discounted_price: float | None, site_price: float | None) -> int | None:
    # SPP in percent, derived from the storefront price
    if not discounted_price or site_price is None:
        return None
    return round((1 - site_price / discounted_price) * 100)


class WbService:
    def __init__(self):
        self.api = WbApi()

    async def collect_prices(self, today: date, account: str):
        token = await get_wb_api_token(account)
        if not token:
            raise Exception(f"WB API token is not configured for {account}")
        goods = await self.api.get_prices(token)
        names = await self.api.get_card_names(token)
        site_prices = await self.api.get_site_prices([item.nmID for item in goods])

        prices: list[WbPrice] = []
        for item in goods:
            name = names.get(item.nmID) or item.vendorCode
            item_site_prices = site_prices.get(item.nmID, {})
            for size in item.sizes or []:
                site_price = item_site_prices.get(size.sizeID)
                if site_price is None and len(item.sizes) == 1 and len(item_site_prices) == 1:
                    site_price = next(iter(item_site_prices.values()))
                prices.append(WbPrice(
                    account=account,
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
                    wb_discount=_wb_discount(size.discountedPrice, site_price),
                    site_price=site_price,
                ))
        # TEMP: debug output of the rows that go to the DB, remove once WB collection is verified
        for price in prices:
            logger.info(
                "TEMP WB row account=%s nm_id=%s vendor_code=%s size=%s name=%s price=%s discounted=%s "
                "club_discounted=%s discount=%s club_discount=%s wb_discount=%s site_price=%s",
                price.account, price.nm_id, price.vendor_code, price.tech_size_name, price.name,
                price.price, price.discounted_price, price.club_discounted_price,
                price.discount, price.club_discount, price.wb_discount, price.site_price,
            )
        batch_size = 40
        for i in range(0, len(prices), batch_size):
            await save_wb_prices(prices[i:i + batch_size])
        logger.info("saved %s WB price rows for %s", len(prices), account)

    async def get_price_change(
        self,
        target_date: date,
        previous_date: date,
        limit: int = 50,
        offset: int = 0,
        vendor_code: str | None = None,
        account: str | None = None,
    ) -> WbPriceChangeResponse:
        async with session_maker() as session, session.begin():
            changes = await get_wb_price_change(
                session, target_date, previous_date, limit, offset, vendor_code, account
            )
            total = await count_wb_price_change(session, target_date, vendor_code, account)
            return WbPriceChangeResponse(price_changes=changes, total=total)

    async def prepare_excel_report(
        self,
        target_date: date,
        vendor_code: str | None = None,
        account: str | None = None,
    ):
        report_date = target_date.strftime("%Y-%m-%d")
        report_date_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        previous_date = (await get_previous_wb_day(target_date, account)) or (target_date - timedelta(days=1))
        base_path = await get_report_path()
        base_path = base_path.value if base_path else "./"
        suffix = f"_{account}" if account else ""
        filename = os.path.join(base_path, f"wb_price_changes_report_{report_date_time}{suffix}.xlsx")

        response = await self.get_price_change(
            target_date=target_date,
            previous_date=previous_date,
            limit=1,
            offset=0,
            vendor_code=vendor_code,
            account=account,
        )
        if not response.price_changes:
            logger.warning("No WB price changes found for %s account=%s", report_date, account)
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
                    account=account,
                )
                if not response.price_changes:
                    break

                df = pd.DataFrame([price.model_dump() for price in response.price_changes])
                column_order = [
                    "account",
                    "vendor_code",
                    "name",
                    "tech_size_name",
                    "yesterday_seller_price",
                    "yesterday_spp",
                    "yesterday_wallet",
                    "today_seller_price",
                    "today_spp",
                    "today_wallet",
                ]
                df = df[column_order]
                df = df.rename(columns={
                    "account": "account",
                    "vendor_code": "vendor_code",
                    "name": "name",
                    "tech_size_name": "size",
                    "today_seller_price": "Цена Продажи " + report_date,
                    "today_spp": "СПП " + report_date,
                    "today_wallet": "WB Кошелёк " + report_date,
                    "yesterday_seller_price": "Цена Продажи " + previous_label,
                    "yesterday_spp": "СПП " + previous_label,
                    "yesterday_wallet": "WB Кошелёк " + previous_label,
                })
                df["Изменение Цены %"] = None

                if first_page:
                    df.to_excel(writer, index=False, sheet_name="Price Changes")
                    sheet = writer.sheets["Price Changes"]
                    for row in range(2, len(df) + 2):
                        sheet.cell(row=row, column=len(df.columns)).value = f"=I{row}/F{row}"
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
                        sheet.cell(row=row, column=len(df.columns)).value = f"=I{row}/F{row}"

                offset += limit
                logger.info("written %s of %s WB rows to excel", offset, response.total)
                if offset >= response.total:
                    break

        logger.info("WB report saved as %s", filename)
        return filename
