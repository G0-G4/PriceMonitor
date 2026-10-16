import asyncio
import json
import logging
import time
from dataclasses import dataclass, replace
from urllib.parse import urlencode

import aiohttp
from yarl import URL

from src.dto.wb_price_dto import WbGoods, WbListGoodsResponse
from src.wb_cities import dests_key

logger = logging.getLogger(__name__)

OFFICIAL_PRICES_URL = "https://discounts-prices-api.wildberries.ru/api/v2/list/goods/filter"
CONTENT_CARDS_URL = "https://content-api.wildberries.ru/content/v2/get/cards/list"
# unofficial storefront API: the buyer price with WB discount (SPP), no auth needed
SITE_CARDS_URL = "https://card.wb.ru/cards/v4/detail"
# same-origin endpoint the storefront itself calls after the wbaas challenge
INTERNAL_CARDS_URL = "https://www.wildberries.ru/__internal/u-card/cards/v4/detail"
SITE_BATCH_SIZE = 100
REQUEST_PAUSE_SECONDS = 0.7
# cities in one wave. A 429 pauses the next wave for every in-flight request.
STOCK_CONCURRENCY = 6
STOCK_ATTEMPTS = 4
STOREFRONT_WAIT_SECONDS = 30
@dataclass(frozen=True)
class WbSiteOffer:
    """Buyer-site price and stock for one size. price is None when the size is listed but not for sale.

    price is the average over the cities that answered for this size, dests_key their
    fingerprint. stock is the reconstructed warehouse quantity for this size. stock_capped
    means WB clipped qty, so stock is a lower bound and the UI shows it as >N.
    """

    price: float | None
    stock: int | None
    stock_capped: bool = False
    dests_key: str | None = None


@dataclass
class SiteScan:
    """Storefront result for one collection, with what kept part of it empty."""

    offers: dict[int, dict[int, WbSiteOffer]]
    # dest -> sizes priced in other cities but not in this one
    missing_price: dict[int, int]
    # sizes left without a price because of missing_price
    missing_sizes: int
    # cities that gave no answer for at least one batch of articles
    failed_dests: list[int]
    storefront_blocked: bool = False


@dataclass(frozen=True)
class SizeStock:
    qty: int
    capped: bool


@dataclass(frozen=True)
class FetchResult:
    payload: dict | None
    status: int
    retry_after: float | None = None


def _as_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _stock_rows(size: dict) -> list:
    stocks = size.get("stocks")
    if isinstance(stocks, list) and stocks:
        return stocks
    # older card payload puts wh/qty on the size itself
    if size.get("wh") is not None:
        return [size]
    return []


def _collect_prices(payload: dict) -> dict[tuple[int, int], float | None]:
    """(nm, optionId) -> buyer price in one city, None when the size is listed but not for sale."""
    prices: dict[tuple[int, int], float | None] = {}
    for product in payload.get("products") or []:
        nm_id = _as_int(product.get("id"))
        if nm_id is None:
            continue
        for size in product.get("sizes") or []:
            option_id = _as_int(size.get("optionId"))
            if option_id is None:
                continue
            product_price = (size.get("price") or {}).get("product")
            prices[(nm_id, option_id)] = product_price / 100 if product_price is not None else None
    return prices


def average_site_price(by_dest: dict[int, float | None], answered: list[int]) -> tuple[float | None, list[int]]:
    """Average buyer price over the cities that answered, and the cities that lack it.

    A size priced in some cities and not in others gets no price: an average over a
    changing set of cities would move without any price change.
    """
    prices = [by_dest.get(dest) for dest in answered]
    priced = [price for price in prices if price is not None]
    if not priced:
        return None, []
    if len(priced) < len(prices):
        return None, [dest for dest in answered if by_dest.get(dest) is None]
    return round(sum(priced) / len(priced), 2), []


def _collect_stock_observations(payload: dict) -> tuple[list[tuple[int, int, int, int]], set[int], set[tuple[int, int]]]:
    """Return (nm, warehouse, optionId, qty) rows, product ids seen, and sizes seen."""
    observations: list[tuple[int, int, int, int]] = []
    seen_products: set[int] = set()
    seen_sizes: set[tuple[int, int]] = set()
    for product in payload.get("products") or []:
        nm_id = _as_int(product.get("id"))
        if nm_id is None:
            continue
        seen_products.add(nm_id)
        for size in product.get("sizes") or []:
            option_id = _as_int(size.get("optionId"))
            if option_id is None:
                continue
            seen_sizes.add((nm_id, option_id))
            for item in _stock_rows(size):
                if not isinstance(item, dict):
                    continue
                qty = _as_int(item.get("qty"))
                warehouse = _as_int(item.get("wh"))
                if qty is None or warehouse is None:
                    continue
                observations.append((nm_id, warehouse, option_id, qty))
    return observations, seen_products, seen_sizes


def aggregate_size_stock(
    observations: list[tuple[int, int, int, int]],
) -> dict[int, dict[int, SizeStock]]:
    """Per size: max qty of each warehouse across cities, then sum the warehouses.

    A qty that equals the highest qty in the whole scan is treated as clipped.
    The size total is then a lower bound, same heuristic Evirma uses.
    """
    ceiling = max((qty for _, _, _, qty in observations), default=0)
    per_warehouse: dict[tuple[int, int, int], int] = {}
    clipped: set[tuple[int, int]] = set()
    for nm_id, warehouse, option_id, qty in observations:
        key = (nm_id, warehouse, option_id)
        previous = per_warehouse.get(key)
        if previous is None or qty > previous:
            per_warehouse[key] = qty
        if ceiling > 0 and qty == ceiling:
            clipped.add((nm_id, option_id))
    result: dict[int, dict[int, SizeStock]] = {}
    for (nm_id, _, option_id), qty in per_warehouse.items():
        sizes = result.setdefault(nm_id, {})
        current = sizes.get(option_id)
        sizes[option_id] = SizeStock(
            qty=(current.qty if current else 0) + qty,
            capped=(nm_id, option_id) in clipped,
        )
    return result


def merge_size_stock(
    offers: dict[int, dict[int, WbSiteOffer]],
    observations: list[tuple[int, int, int, int]],
    seen_products: set[int],
    seen_sizes: set[tuple[int, int]],
) -> None:
    """Write warehouse stock. Sizes the scan did not return stay empty."""
    stocks = aggregate_size_stock(observations)
    for nm_id in seen_products:
        size_stocks = stocks.get(nm_id, {})
        current = offers.setdefault(nm_id, {})
        for option_id, offer in list(current.items()):
            found = size_stocks.get(option_id)
            if found is not None:
                current[option_id] = replace(offer, stock=found.qty, stock_capped=found.capped)
            elif (nm_id, option_id) in seen_sizes:
                current[option_id] = replace(offer, stock=0, stock_capped=False)
            else:
                current[option_id] = replace(offer, stock=None, stock_capped=False)
        for option_id, found in size_stocks.items():
            if option_id not in current:
                current[option_id] = WbSiteOffer(None, found.qty, found.capped)


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

    def _stock_cards_url(self, base: str, nm_ids: list[int], dest: int) -> str:
        # hide_dtype=13 is the warehouse-stock request Evirma sends. Its buyer price
        # matched the hide_vflags/mtype price request for all 1165 sizes on 2026-10-16,
        # so one request per city gives both price and stock.
        query = urlencode({
            "appType": 1,
            "curr": "rub",
            "dest": dest,
            "spp": 30,
            "hide_dtype": 13,
            "ab_testing": "false",
            "lang": "ru",
            "nm": ";".join(str(nm_id) for nm_id in nm_ids),
        }, safe=";")
        return f"{base}?{query}"

    async def get_site_prices(self, nm_ids: list[int], dests: list[int]) -> SiteScan:
        """nm_id -> {optionId (= sizeID of the official API): buyer price and stock} over dests.

        A size with no buyer price is still returned, so a missing SPP can be told
        apart from a storefront request that failed.
        """
        scan = await self._get_site_prices_http(nm_ids, dests)
        if scan.offers:
            logger.info("WB site prices via HTTP: %s of %s nm_ids", len(scan.offers), len(nm_ids))
            return scan
        logger.warning("HTTP got no WB site prices (card.wb.ru often returns 403), retrying via Chrome")
        scan = await self._get_site_prices_chrome(nm_ids, dests)
        logger.info("WB site prices via Chrome: %s of %s nm_ids", len(scan.offers), len(nm_ids))
        if not scan.offers:
            logger.error("WB site prices empty — SPP and wallet columns will be blank")
        return scan

    async def _get_site_prices_http(self, nm_ids: list[int], dests: list[int]) -> SiteScan:
        timeout = aiohttp.ClientTimeout(total=60)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Accept-Language": "ru-RU,ru;q=0.9",
            "Referer": "https://www.wildberries.ru/",
        }

        async def fetch_many(urls: list[str]) -> list[FetchResult]:
            return list(await asyncio.gather(*(self._get_stock_once(session, url) for url in urls)))

        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            return await self._scan_cities(nm_ids, dests, fetch_many, SITE_CARDS_URL)

    async def _get_stock_once(self, session: aiohttp.ClientSession, url: str) -> FetchResult:
        request_url = URL(url, encoded=True)
        try:
            async with session.get(request_url) as resp:
                text = await resp.text()
                if resp.status == 429:
                    return FetchResult(None, 429, _retry_delay(resp, 0))
                if resp.status >= 400:
                    return FetchResult(None, resp.status)
                return FetchResult(json.loads(text), 200)
        except json.JSONDecodeError:
            return FetchResult(None, 0)
        except Exception as exc:
            logger.warning("WB stock request failed: %s", exc)
            return FetchResult(None, 0)

    async def _scan_cities(self, nm_ids, dests: list[int], fetch_many, base: str) -> SiteScan:
        # One request is one city and one batch. A wave sends STOCK_CONCURRENCY at once.
        # Any 429 holds the following wave; the limited requests go back in the queue.
        batches = [nm_ids[i:i + SITE_BATCH_SIZE] for i in range(0, len(nm_ids), SITE_BATCH_SIZE)]
        pending = [
            [dest, self._stock_cards_url(base, batch, dest), 0, batch_no]
            for dest in dests
            for batch_no, batch in enumerate(batches)
        ]
        observations: list[tuple[int, int, int, int]] = []
        seen_products: set[int] = set()
        seen_sizes: set[tuple[int, int]] = set()
        # (nm, optionId) -> dest -> price, and which cities answered each batch
        prices: dict[tuple[int, int], dict[int, float | None]] = {}
        answered: list[list[int]] = [[] for _ in batches]
        failed: set[int] = set()
        first_dest = dests[0]
        first_left = len(batches)
        first_ok = False
        limited = 0
        backoff = 1.0
        started = time.monotonic()
        logger.info(
            "loading WB prices and stock for %s nm_ids across %s dests, %s at a time",
            len(nm_ids),
            len(dests),
            STOCK_CONCURRENCY,
        )
        wave_no = 0
        while pending:
            wave_no += 1
            wave = pending[:STOCK_CONCURRENCY]
            pending = pending[STOCK_CONCURRENCY:]
            try:
                fetched = await fetch_many([url for _, url, _, _ in wave])
            except Exception:
                logger.warning("WB stock wave %s failed", wave_no, exc_info=True)
                fetched = [FetchResult(None, 0) for _ in wave]
            if len(fetched) != len(wave):
                fetched = list(fetched) + [FetchResult(None, 0)] * (len(wave) - len(fetched))
            retry = []
            retry_after = 0.0
            wave_ok = 0
            wave_limited = 0
            for (dest, url, attempt, batch_no), result in zip(wave, fetched):
                if result.status == 429:
                    limited += 1
                    wave_limited += 1
                    if result.retry_after:
                        retry_after = max(retry_after, result.retry_after)
                    if attempt + 1 < STOCK_ATTEMPTS:
                        retry.append([dest, url, attempt + 1, batch_no])
                    else:
                        logger.warning("WB stock dest=%s stayed rate limited", dest)
                        failed.add(dest)
                        if dest == first_dest:
                            first_left -= 1
                    continue
                if not result.payload:
                    failed.add(dest)
                    if dest == first_dest:
                        first_left -= 1
                    if result.status not in (0, 200):
                        logger.warning("WB stock dest=%s status=%s", dest, result.status)
                    continue
                answered[batch_no].append(dest)
                for key, price in _collect_prices(result.payload).items():
                    prices.setdefault(key, {})[dest] = price
                obs, products, sizes = _collect_stock_observations(result.payload)
                observations.extend(obs)
                seen_products.update(products)
                seen_sizes.update(sizes)
                wave_ok += 1
                if dest == first_dest:
                    first_left -= 1
                    if products:
                        first_ok = True
            logger.info(
                "WB stock wave %s: ok %s, 429 %s, left %s, products %s",
                wave_no,
                wave_ok,
                wave_limited,
                len(pending) + len(retry),
                len(seen_products),
            )
            if first_left <= 0 and not first_ok:
                logger.error("WB storefront answered nothing for dest=%s, site prices and stock will be empty", first_dest)
                return SiteScan({}, {}, 0, list(dests))
            if retry:
                delay = retry_after if retry_after > 0 else backoff
                logger.warning(
                    "WB stock rate limited on %s request(s), pausing %.1f s",
                    len(retry),
                    delay,
                )
                await asyncio.sleep(delay)
                backoff = min(max(backoff * 2, delay), 30.0)
                pending = retry + pending
            else:
                backoff = 1.0
        if not seen_products:
            logger.error("WB storefront returned no products, site prices and stock will be empty")
            return SiteScan({}, {}, 0, sorted(failed))
        batch_of = {nm_id: batch_no for batch_no, batch in enumerate(batches) for nm_id in batch}
        offers: dict[int, dict[int, WbSiteOffer]] = {}
        missing_price: dict[int, int] = {}
        missing_sizes = 0
        for (nm_id, option_id), by_dest in prices.items():
            cities = answered[batch_of[nm_id]] if nm_id in batch_of else []
            price, missing = average_site_price(by_dest, cities)
            if missing:
                missing_sizes += 1
            for dest in missing:
                missing_price[dest] = missing_price.get(dest, 0) + 1
            offers.setdefault(nm_id, {})[option_id] = WbSiteOffer(price, None, dests_key=dests_key(cities))
        merge_size_stock(offers, observations, seen_products, seen_sizes)
        capped = sum(1 for sizes in offers.values() for offer in sizes.values() if offer.stock_capped)
        logger.info(
            "WB warehouse stock matched %s of %s nm_ids, %s sizes clipped, %.1f s, 429s %s",
            len(seen_products),
            len(nm_ids),
            capped,
            time.monotonic() - started,
            limited,
        )
        if failed:
            logger.warning("WB storefront gave no answer for dests %s", sorted(failed))
        return SiteScan(offers, missing_price, missing_sizes, sorted(failed))

    async def _wait_for_storefront(self, page) -> bool:
        # wbaas answers 498 and only reloads the real site after its script finishes.
        # The challenge document title is "...", the shop title contains Wildberries.
        for _ in range(STOREFRONT_WAIT_SECONDS):
            try:
                title = await page.title()
            except Exception:
                title = ""
            if "Wildberries" in title or "Вайлдберриз" in title:
                return True
            await asyncio.sleep(1)
        return False

    async def _minimize_window(self, browser) -> None:
        # Headless Chrome stays on the wbaas challenge. A real window minimized
        # off-screen still finishes it, without sitting on the desktop.
        try:
            cdp = await browser.new_browser_cdp_session()
            targets = await cdp.send("Target.getTargets")
            target_id = next(
                item["targetId"]
                for item in targets["targetInfos"]
                if item["type"] == "page"
            )
            window = await cdp.send("Browser.getWindowForTarget", {"targetId": target_id})
            await cdp.send("Browser.setWindowBounds", {
                "windowId": window["windowId"],
                "bounds": {"windowState": "minimized"},
            })
        except Exception:
            logger.warning("could not minimize the WB Chrome window", exc_info=True)

    async def _get_site_prices_chrome(self, nm_ids: list[int], dests: list[int]) -> SiteScan:
        # card.wb.ru stays 403. Prices come from the same-origin __internal/u-card
        # endpoint after the wbaas challenge, which headless Chrome does not finish.
        from playwright.async_api import async_playwright

        scan = SiteScan({}, {}, 0, list(dests))
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(
            channel="chrome",
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--window-position=-2400,-2400",
                "--window-size=900,700",
                "--start-minimized",
            ],
        )
        context = await browser.new_context(locale="ru-RU")
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = await context.new_page()
        await self._minimize_window(browser)
        try:
            logger.info("opening a minimized Chrome to pass the WB antibot check")
            await page.goto("https://www.wildberries.ru/", wait_until="domcontentloaded", timeout=60_000)
            if not await self._wait_for_storefront(page):
                logger.error("WB antibot challenge did not finish, SPP will be empty")
                return SiteScan({}, {}, 0, [], storefront_blocked=True)
            session = await page.evaluate(
                """() => {
                    const hostVersion = window.__HOST_VERSION__;
                    return {
                        deviceid: localStorage.getItem('wbx__sessionID') || '',
                        spa: typeof hostVersion === 'string' ? hostVersion : '',
                    };
                }"""
            )
            # cities are the account's, not the session geolocation: WB picks that by IP
            # and it changed between runs
            deviceid = session.get("deviceid") or ""
            spa = session.get("spa") or ""
            logger.info(
                "WB storefront ready, %s dests spa=%s deviceid=%s",
                len(dests),
                spa or "missing",
                "yes" if deviceid else "no",
            )
            scan = await self._scan_cities(
                nm_ids,
                dests,
                lambda urls: self._chrome_fetch_many(page, urls, deviceid, spa),
                INTERNAL_CARDS_URL,
            )
        except Exception:
            logger.exception("Chrome fetch of WB site prices failed")
        finally:
            await browser.close()
            await pw.stop()
        return scan

    async def _chrome_fetch_many(self, page, urls: list[str], deviceid: str, spa: str) -> list[FetchResult]:
        # One evaluate so the browser fires the wave together. Separate evaluates
        # would wait for each fetch to finish before the next one starts.
        rows = await page.evaluate(
            """async ({urls, deviceid, spa}) => {
                const headers = {
                    accept: '*/*',
                    'x-requested-with': 'XMLHttpRequest',
                };
                if (deviceid) headers.deviceid = deviceid;
                if (spa) headers['x-spa-version'] = spa;
                return await Promise.all(urls.map(async (url) => {
                    try {
                        const response = await fetch(url, {credentials: 'include', headers});
                        const retryAfter = response.headers.get('x-ratelimit-retry')
                            || response.headers.get('retry-after');
                        return { status: response.status, body: await response.text(), retryAfter };
                    } catch (error) {
                        return { status: 0, body: String(error), retryAfter: null };
                    }
                }));
            }""",
            {"urls": urls, "deviceid": deviceid, "spa": spa},
        )
        fetched: list[FetchResult] = []
        for row in rows or []:
            status = int(row.get("status") or 0)
            body = row.get("body") or ""
            retry_after = None
            try:
                if row.get("retryAfter") not in (None, ""):
                    retry_after = float(row["retryAfter"])
            except (TypeError, ValueError):
                retry_after = None
            if status != 200:
                if status != 429:
                    logger.warning("Chrome fetch failed status=%s body=%s", status, body[:300])
                fetched.append(FetchResult(None, status, retry_after))
                continue
            try:
                fetched.append(FetchResult(json.loads(body), 200))
            except json.JSONDecodeError:
                logger.warning("Chrome fetch returned non-json body=%s", body[:300])
                fetched.append(FetchResult(None, 0))
        return fetched

    async def _get_json(self, session: aiohttp.ClientSession, url: str, params: dict | None = None) -> dict:
        # a fully built stock URL already contains raw ';'. aiohttp would encode
        # it to %3B and WB would return no products.
        request_url = URL(url, encoded=True) if params is None else url
        for attempt in range(5):
            async with session.get(request_url, params=params) as resp:
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
