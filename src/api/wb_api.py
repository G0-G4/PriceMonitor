import asyncio
import json
import logging

import aiohttp

from src.browser_request_sender import BrowserRequestSender, ReLoginRequiredError
from src.dto.wb_price_dto import (
    WbDiscountOnSite,
    WbDiscountOnSiteResponse,
    WbGoods,
    WbListGoodsResponse,
)

logger = logging.getLogger(__name__)

OFFICIAL_PRICES_URL = "https://discounts-prices-api.wildberries.ru/api/v2/list/goods/filter"
PORTAL_DISCOUNT_URL = (
    "https://discounts-prices.wildberries.ru/ns/dp-api/discounts-prices/suppliers/api/v1/list/goods/filter"
)
CONTENT_CARDS_URL = "https://content-api.wildberries.ru/content/v2/get/cards/list"
REQUEST_PAUSE_SECONDS = 0.7


class WbApi:
    def __init__(self, request_sender: BrowserRequestSender):
        self.request_sender = request_sender

    async def open_browser(self):
        await self.request_sender.init()

    async def close_browser(self):
        await self.request_sender.close()

    async def get_prices(self, token: str, limit: int = 1000) -> list[WbGoods]:
        goods: list[WbGoods] = []
        offset = 0
        timeout = aiohttp.ClientTimeout(total=60)
        headers = {"Authorization": token}
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            while True:
                payload = await self._get_json(
                    session,
                    OFFICIAL_PRICES_URL,
                    params={"limit": limit, "offset": offset},
                )
                response = WbListGoodsResponse.model_validate(payload)
                if response.error:
                    raise Exception(response.errorText or "WB prices API error")
                page = response.data.listGoods if response.data else []
                if not page:
                    break
                goods.extend(page)
                offset += len(page)
                logger.info("loaded %s WB prices, offset=%s", len(page), offset)
                await asyncio.sleep(REQUEST_PAUSE_SECONDS)
        return goods

    async def get_card_names(self, token: str) -> dict[int, str]:
        names: dict[int, str] = {}
        cursor: dict = {"limit": 100}
        timeout = aiohttp.ClientTimeout(total=60)
        headers = {"Authorization": token, "Content-Type": "application/json"}
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                while True:
                    payload = await self._post_json(
                        session,
                        CONTENT_CARDS_URL,
                        body={"settings": {"cursor": cursor, "filter": {"withPhoto": -1}}},
                    )
                    cards = payload.get("cards") or []
                    if not cards:
                        break
                    for card in cards:
                        nm_id = card.get("nmID")
                        title = card.get("title") or card.get("name")
                        if nm_id is not None and title:
                            names[int(nm_id)] = title
                    next_cursor = payload.get("cursor") or {}
                    if not next_cursor.get("nmID"):
                        break
                    cursor = {
                        "limit": 100,
                        "updatedAt": next_cursor.get("updatedAt"),
                        "nmID": next_cursor.get("nmID"),
                    }
                    await asyncio.sleep(REQUEST_PAUSE_SECONDS)
        except Exception:
            logger.exception("failed to load WB card names, vendor_code will be used")
            return names
        logger.info("loaded %s WB card names", len(names))
        return names

    async def get_discount_on_site(self, limit: int = 100) -> list[WbDiscountOnSite]:
        discounts: list[WbDiscountOnSite] = []
        offset = 0
        extra_headers = await self._portal_headers()
        while True:
            payload = await self.request_sender.send_context_request(
                "POST",
                PORTAL_DISCOUNT_URL,
                {"limit": limit, "offset": offset, "vendorCode": None},
                extra_headers=extra_headers,
            )
            response = WbDiscountOnSiteResponse.model_validate(payload)
            if response.error:
                raise Exception(response.errorText or "WB discountOnSite API error")
            page = response.data.listGoods if response.data else []
            if not page:
                break
            discounts.extend(page)
            offset += len(page)
            logger.info("loaded %s WB discountOnSite rows, offset=%s", len(page), offset)
            await asyncio.sleep(REQUEST_PAUSE_SECONDS)
        return discounts

    async def _portal_headers(self) -> dict[str, str]:
        headers = {
            "Origin": "https://seller.wildberries.ru",
            "Referer": "https://seller.wildberries.ru/",
        }
        storage = await self.request_sender.get_local_storage()
        for key, value in storage.items():
            if not value:
                continue
            lower = key.lower()
            if "authorizev3" in lower:
                headers["authorizev3"] = value
            elif "token" in lower and str(value).startswith("eyJ") and "authorizev3" not in headers:
                headers["authorizev3"] = value
        return headers

    async def _get_json(self, session: aiohttp.ClientSession, url: str, params: dict) -> dict:
        for attempt in range(5):
            async with session.get(url, params=params) as resp:
                text = await resp.text()
                if resp.status == 429:
                    await asyncio.sleep(2 ** attempt)
                    continue
                if resp.status in (401, 403):
                    raise ReLoginRequiredError(text)
                if resp.status >= 400:
                    raise Exception(f"WB API {resp.status}: {text[:500]}")
                return json.loads(text)
        raise Exception("WB API rate limited")

    async def _post_json(self, session: aiohttp.ClientSession, url: str, body: dict) -> dict:
        for attempt in range(5):
            async with session.post(url, json=body) as resp:
                text = await resp.text()
                if resp.status == 429:
                    await asyncio.sleep(2 ** attempt)
                    continue
                if resp.status in (401, 403):
                    raise ReLoginRequiredError(text)
                if resp.status >= 400:
                    raise Exception(f"WB API {resp.status}: {text[:500]}")
                return json.loads(text)
        raise Exception("WB API rate limited")
