import asyncio
import json
import logging

import aiohttp

from src.dto.wb_price_dto import WbGoods, WbListGoodsResponse

logger = logging.getLogger(__name__)

OFFICIAL_PRICES_URL = "https://discounts-prices-api.wildberries.ru/api/v2/list/goods/filter"
CONTENT_CARDS_URL = "https://content-api.wildberries.ru/content/v2/get/cards/list"
# unofficial storefront API: the buyer price with WB discount (SPP), no auth needed
SITE_CARDS_URL = "https://card.wb.ru/cards/v4/detail"
# delivery region the storefront prices are taken for, same as wildberries.ru uses for Moscow
SITE_DEST = "1259571083"
SITE_BATCH_SIZE = 100
REQUEST_PAUSE_SECONDS = 0.7


def _retry_delay(resp: aiohttp.ClientResponse, attempt: int) -> float:
    # WB tells how long to wait in X-Ratelimit-Retry, retrying earlier gets 429 again
    try:
        return float(resp.headers["X-Ratelimit-Retry"]) + 0.5
    except (KeyError, ValueError):
        return 2 ** attempt


class WbApi:
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
                        body={"settings": {
                            "sort": {"ascending": True},
                            "cursor": cursor,
                            "filter": {"withPhoto": -1},
                        }},
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
                    # per the docs the last page is the one where total < limit
                    total = next_cursor.get("total")
                    if not next_cursor.get("nmID") or (total is not None and total < 100):
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

    async def get_site_prices(self, nm_ids: list[int]) -> dict[int, dict[int, float]]:
        """nm_id -> {optionId (= sizeID of the official API): buyer price in rubles}. Out of stock sizes have no price."""
        prices: dict[int, dict[int, float]] = {}
        timeout = aiohttp.ClientTimeout(total=60)
        headers = {"User-Agent": "Mozilla/5.0"}
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            for i in range(0, len(nm_ids), SITE_BATCH_SIZE):
                batch = nm_ids[i:i + SITE_BATCH_SIZE]
                try:
                    payload = await self._get_json(session, SITE_CARDS_URL, params={
                        "appType": 1,
                        "curr": "rub",
                        "dest": SITE_DEST,
                        "spp": 30,
                        "nm": ";".join(str(nm_id) for nm_id in batch),
                    })
                except Exception:
                    logger.exception("failed to load WB site prices for %s nm_ids, SPP will be empty", len(batch))
                    continue
                for product in payload.get("products") or []:
                    sizes = prices.setdefault(int(product["id"]), {})
                    for size in product.get("sizes") or []:
                        product_price = (size.get("price") or {}).get("product")
                        if product_price is not None and size.get("optionId") is not None:
                            sizes[int(size["optionId"])] = product_price / 100
                logger.info("loaded WB site prices, %s/%s nm_ids", min(i + SITE_BATCH_SIZE, len(nm_ids)), len(nm_ids))
                await asyncio.sleep(REQUEST_PAUSE_SECONDS)
        return prices

    async def _get_json(self, session: aiohttp.ClientSession, url: str, params: dict) -> dict:
        for attempt in range(5):
            async with session.get(url, params=params) as resp:
                text = await resp.text()
                if resp.status == 429:
                    delay = _retry_delay(resp, attempt)
                    logger.warning("WB API rate limited on %s, retry in %s s", url, delay)
                    await asyncio.sleep(delay)
                    continue
                if resp.status >= 400:
                    raise Exception(f"WB API {resp.status}: {text[:500]}")
                return json.loads(text)
        raise Exception("WB API rate limited")

    async def _post_json(self, session: aiohttp.ClientSession, url: str, body: dict) -> dict:
        for attempt in range(5):
            async with session.post(url, json=body) as resp:
                text = await resp.text()
                if resp.status == 429:
                    delay = _retry_delay(resp, attempt)
                    logger.warning("WB API rate limited on %s, retry in %s s", url, delay)
                    await asyncio.sleep(delay)
                    continue
                if resp.status >= 400:
                    raise Exception(f"WB API {resp.status}: {text[:500]}")
                return json.loads(text)
        raise Exception("WB API rate limited")
