from datetime import datetime, date, timedelta
import asyncio
import logging
import os

import pandas as pd
from openpyxl.utils import get_column_letter

from src.api.wb_api import SiteScan, StockResult, WbApi
from src.dto.wb_price_dto import WbPriceChangeResponse
from src.models.database import session_maker
from src.models.wb_price import WbPrice
from src.persistence.parameters_db import get_report_path, get_wb_api_token, get_wb_dests
from src.persistence.wb_price_db import (
    count_wb_price_change,
    get_previous_wb_day,
    get_wb_price_change,
    save_wb_prices,
)
from src.wb_cities import city_name

logger = logging.getLogger(__name__)


def _stock_cell(stock: int | None, capped: bool):
    # >N only on days collected from the storefront, where WB clipped qty
    if stock is None:
        return None
    if capped:
        return f">{stock}"
    return stock


def _wb_discount(discounted_price: float | None, site_price: float | None) -> int | None:
    # SPP in percent, derived from the storefront price
    if not discounted_price or site_price is None:
        return None
    return round((1 - site_price / discounted_price) * 100)


def _site_warnings(scan: SiteScan, dests: list[int]) -> list[str]:
    """What left buyer prices empty, for the collection task."""
    if scan.storefront_blocked:
        return ["WB storefront did not pass the antibot check, buyer prices and SPP are empty"]
    warnings = []
    if not scan.offers and len(scan.failed_dests) == len(dests):
        warnings.append("WB storefront answered for no city, buyer prices and SPP are empty")
    elif scan.failed_dests:
        names = ", ".join(city_name(dest) for dest in scan.failed_dests)
        warnings.append(f"WB did not answer for {names}, prices use the other cities")
    if scan.missing_sizes:
        by_city = ", ".join(
            f"{city_name(dest)} {count}"
            for dest, count in sorted(scan.missing_price.items(), key=lambda item: -item[1])
        )
        warnings.append(f"{scan.missing_sizes} sizes have no price in some cities ({by_city}), their SPP is empty")
    return warnings


_STOCK_SOURCES = {"fbs": "seller warehouses (FBS)", "fbo": "WB warehouses (FBO)"}


def _stock_warnings(result: StockResult) -> list[str]:
    """Why stock is empty: what to fix in the token, or which source failed."""
    warnings = []
    for error in result.errors:
        if error.status in (401, 403) and error.source == "fbs":
            warnings.append("WB stock: the token needs the Marketplace category")
        elif error.status in (401, 403):
            warnings.append(
                "WB stock on WB warehouses: the token must be Personal (or Service) with the Analytics category"
            )
        else:
            status = error.status or "network error"
            warnings.append(f"WB stock was not loaded from {_STOCK_SOURCES[error.source]}: {status}")
    if warnings:
        warnings[-1] += ", stock is empty"
    return warnings


class WbService:
    def __init__(self):
        self.api = WbApi()

    async def collect_prices(self, today: date, account: str) -> list[str]:
        """Collect and save the account's prices. Returns warnings about data left empty."""
        token = await get_wb_api_token(account)
        if not token:
            raise Exception(f"WB API token is not configured for {account}")
        goods = await self.api.get_prices(token)
        names = await self.api.get_card_names(token)
        dests = await get_wb_dests(account)
        nm_ids = [item.nmID for item in goods]
        chrt_ids = [size.sizeID for item in goods for size in item.sizes or []]
        # FBO pauses 20 s between requests, so stock loads while the storefront is scanned
        stock, scan = await asyncio.gather(
            self.api.get_stocks(token, nm_ids, chrt_ids),
            self.api.get_site_prices(nm_ids, dests),
        )
        site_prices = scan.offers
        logger.info(
            "WB storefront matched %s of %s nm_ids for %s",
            len(site_prices),
            len(goods),
            account,
        )

        prices: list[WbPrice] = []
        for item in goods:
            name = names.get(item.nmID) or item.vendorCode
            item_site_prices = site_prices.get(item.nmID, {})
            for size in item.sizes or []:
                offer = item_site_prices.get(size.sizeID)
                if offer is None and len(item.sizes) == 1 and len(item_site_prices) == 1:
                    offer = next(iter(item_site_prices.values()))
                site_price = offer.price if offer else None
                # a size on no warehouse is 0, but only when both sources answered
                site_stock = stock.stocks.get(size.sizeID, 0) if stock.stocks is not None else None
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
                    site_stock=site_stock,
                    site_stock_capped=0 if site_stock is not None else None,
                    site_dests_key=offer.dests_key if offer else None,
                ))
        batch_size = 40
        for i in range(0, len(prices), batch_size):
            await save_wb_prices(prices[i:i + batch_size])
        logger.info("saved %s WB price rows for %s", len(prices), account)
        warnings = _site_warnings(scan, dests) + _stock_warnings(stock)
        for warning in warnings:
            logger.warning("WB %s: %s", account, warning)
        return warnings

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

                rows = []
                for price in response.price_changes:
                    row = price.model_dump()
                    row["yesterday_stock"] = _stock_cell(price.yesterday_stock, price.yesterday_stock_capped)
                    row["today_stock"] = _stock_cell(price.today_stock, price.today_stock_capped)
                    rows.append(row)
                df = pd.DataFrame(rows)
                column_order = [
                    "account",
                    "vendor_code",
                    "nm_id",
                    "name",
                    "tech_size_name",
                    "yesterday_stock",
                    "yesterday_seller_price",
                    "yesterday_spp",
                    "yesterday_wallet",
                    "today_stock",
                    "today_seller_price",
                    "today_spp",
                    "today_wallet",
                ]
                df = df[column_order]
                renamed = {
                    "account": "account",
                    "vendor_code": "vendor_code",
                    "nm_id": "Артикул WB",
                    "name": "name",
                    "tech_size_name": "size",
                    "yesterday_stock": "Остаток " + previous_label,
                    "today_stock": "Остаток " + report_date,
                    "today_seller_price": "Цена Продажи " + report_date,
                    "today_spp": "СПП " + report_date,
                    "today_wallet": "WB Кошелёк " + report_date,
                    "yesterday_seller_price": "Цена Продажи " + previous_label,
                    "yesterday_spp": "СПП " + previous_label,
                    "yesterday_wallet": "WB Кошелёк " + previous_label,
                }
                yesterday_spp_col = get_column_letter(column_order.index("yesterday_spp") + 1)
                today_spp_col = get_column_letter(column_order.index("today_spp") + 1)
                df = df.rename(columns=renamed)
                df["Изменение Цены %"] = None

                if first_page:
                    df.to_excel(writer, index=False, sheet_name="Price Changes")
                    sheet = writer.sheets["Price Changes"]
                    for row, price in zip(range(2, len(df) + 2), response.price_changes):
                        if not price.dests_changed:
                            sheet.cell(row=row, column=len(df.columns)).value = f"={today_spp_col}{row}/{yesterday_spp_col}{row}"
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
                    for row, price in zip(range(startrow + 1, startrow + len(df) + 1), response.price_changes):
                        if not price.dests_changed:
                            sheet.cell(row=row, column=len(df.columns)).value = f"={today_spp_col}{row}/{yesterday_spp_col}{row}"

                offset += limit
                logger.info("written %s of %s WB rows to excel", offset, response.total)
                if offset >= response.total:
                    break

        logger.info("WB report saved as %s", filename)
        return filename
