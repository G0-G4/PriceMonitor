import asyncio
import json
import logging
from urllib.parse import urlencode

import aiohttp

from src.config import HEADLESS_BROWSER
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

    def _site_cards_url(self, nm_ids: list[int]) -> str:
        query = urlencode({
            "appType": 1,
            "curr": "rub",
            "dest": SITE_DEST,
            "spp": 30,
            "nm": ";".join(str(nm_id) for nm_id in nm_ids),
        })
        return f"{SITE_CARDS_URL}?{query}"

    def _parse_site_payload(self, payload: dict, prices: dict[int, dict[int, float]]) -> int:
        added = 0
        for product in payload.get("products") or []:
            sizes = prices.setdefault(int(product["id"]), {})
            for size in product.get("sizes") or []:
                product_price = (size.get("price") or {}).get("product")
                if product_price is not None and size.get("optionId") is not None:
                    sizes[int(size["optionId"])] = product_price / 100
                    added += 1
        return added

    async def get_site_prices(self, nm_ids: list[int]) -> dict[int, dict[int, float]]:
        """nm_id -> {optionId (= sizeID of the official API): buyer price in rubles}. Out of stock sizes have no price."""
        prices = await self._get_site_prices_http(nm_ids)
        if prices:
            logger.info("WB site prices via HTTP: %s of %s nm_ids", len(prices), len(nm_ids))
            return prices
        logger.warning("HTTP got no WB site prices (card.wb.ru often returns 403), retrying via Chrome")
        prices = await self._get_site_prices_chrome(nm_ids)
        logger.info("WB site prices via Chrome: %s of %s nm_ids", len(prices), len(nm_ids))
        if not prices:
            logger.error("WB site prices empty — SPP and wallet columns will be blank")
        return prices

    async def _get_site_prices_http(self, nm_ids: list[int]) -> dict[int, dict[int, float]]:
        prices: dict[int, dict[int, float]] = {}
        timeout = aiohttp.ClientTimeout(total=60)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Accept-Language": "ru-RU,ru;q=0.9",
            "Referer": "https://www.wildberries.ru/",
        }
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
                    logger.warning(
                        "failed to load WB site prices over HTTP for %s nm_ids",
                        len(batch),
                        exc_info=True,
                    )
                    continue
                self._parse_site_payload(payload, prices)
                await asyncio.sleep(REQUEST_PAUSE_SECONDS)
        return prices

    async def _get_site_prices_chrome(self, nm_ids: list[int]) -> dict[int, dict[int, float]]:
        from playwright.async_api import async_playwright

        prices: dict[int, dict[int, float]] = {}
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(
            channel="chrome",
            headless=HEADLESS_BROWSER,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(locale="ru-RU")
        page = await context.new_page()
        try:
            await page.goto("https://www.wildberries.ru/", wait_until="domcontentloaded", timeout=60_000)
            await asyncio.sleep(2)
            for i in range(0, len(nm_ids), SITE_BATCH_SIZE):
                batch = nm_ids[i:i + SITE_BATCH_SIZE]
                url = self._site_cards_url(batch)
                result = await page.evaluate(
                    """async (url) => {
                        try {
                            const response = await fetch(url);
                            return { status: response.status, body: await response.text() };
                        } catch (error) {
                            return { status: 0, body: String(error) };
                        }
                    }""",
                    url,
                )
                status = result.get("status")
                body = result.get("body") or ""
                if status != 200:
                    logger.warning(
                        "Chrome fetch of WB site prices failed status=%s body=%s",
                        status,
                        body[:300],
                    )
                    continue
                payload = json.loads(body)
                added = self._parse_site_payload(payload, prices)
                logger.info(
                    "loaded WB site prices via Chrome, %s/%s nm_ids, %s sizes",
                    min(i + SITE_BATCH_SIZE, len(nm_ids)),
                    len(nm_ids),
                    added,
                )
                await asyncio.sleep(REQUEST_PAUSE_SECONDS)
        except Exception:
            logger.exception("Chrome fetch of WB site prices failed")
        finally:
            await browser.close()
            await pw.stop()
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
