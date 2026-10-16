import asyncio
import json
import logging
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import aiohttp
from yarl import URL

from src.dto.wb_price_dto import WbGoods, WbListGoodsResponse

logger = logging.getLogger(__name__)

OFFICIAL_PRICES_URL = "https://discounts-prices-api.wildberries.ru/api/v2/list/goods/filter"
CONTENT_CARDS_URL = "https://content-api.wildberries.ru/content/v2/get/cards/list"
# unofficial storefront API: the buyer price with WB discount (SPP), no auth needed
SITE_CARDS_URL = "https://card.wb.ru/cards/v4/detail"
# same-origin endpoint the storefront itself calls after the wbaas challenge
INTERNAL_CARDS_URL = "https://www.wildberries.ru/__internal/u-card/cards/v4/detail"
# delivery region the storefront prices are taken for: Moscow as Evirma 2.60.2 queries it
SITE_DEST = "-1257786"
SITE_BATCH_SIZE = 100
REQUEST_PAUSE_SECONDS = 0.7
# cities in one wave. A 429 pauses the next wave for every in-flight request.
STOCK_CONCURRENCY = 6
STOCK_ATTEMPTS = 4
STOREFRONT_WAIT_SECONDS = 30
# Cities Evirma 2.60.2 queries by default for warehouse stock (its seo destinations).
# A warehouse reports qty only for regions it delivers to, so one Moscow dest undercounts.
STOCK_DESTS: tuple[int, ...] = (
    -364001,  # Москва, центр
    123586098,  # Балашиха
    -3339991,  # Смоленск
    -1263279,  # Тверь
    -5817685,  # Рязань
    12358385,  # Воронеж
    -3351953,  # Ярославль
    -1187265,  # Санкт-Петербург
    -2448021,  # Тольятти
    12358461,  # Саратов
    -1257218,  # Самара
    12358495,  # Уфа
    -2133462,  # Казань
    -2689194,  # Новокузнецк
    12358535,  # Нижний Новгород
    12358361,  # Пермь
    -4039466,  # Волгоград
    -2228364,  # Ростов-на-Дону
    12358058,  # Краснодар
    -5921133,  # Махачкала
    -3888337,  # Грозный
    123585969,  # Магнитогорск
    -897988,  # Тюмень
    -1579833,  # Челябинск
    -5803327,  # Екатеринбург
    -3902910,  # Омск
    -364763,  # Новосибирск
    12356481,  # Красноярск
    -1785058,  # Хабаровск
    123586013,  # Владивосток
    -5827722,  # Иркутск
    -59208,  # Минск
    85,  # Астана
)


@dataclass(frozen=True)
class WbSiteOffer:
    """Buyer-site price and stock for one size. price is None when the size is listed but not for sale.

    stock is the reconstructed warehouse quantity for this size. stock_capped means WB clipped
    qty, so stock is a lower bound and the UI shows it as >N.
    """

    price: float | None
    stock: int | None
    stock_capped: bool = False


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
                current[option_id] = WbSiteOffer(offer.price, found.qty, found.capped)
            elif (nm_id, option_id) in seen_sizes:
                current[option_id] = WbSiteOffer(offer.price, 0, False)
            else:
                current[option_id] = WbSiteOffer(offer.price, None, False)
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

    def _internal_cards_url(self, nm_ids: list[int], dest: str) -> str:
        # nm is joined by raw ';'. urlencode would turn that into %3B and WB returns nothing.
        query = urlencode({
            "appType": 1,
            "curr": "rub",
            "dest": dest,
            "spp": 30,
            "hide_vflags": 4294967296,
            "mtype": 257,
            "lang": "ru",
            "ab_testing": "false",
            "nm": ";".join(str(nm_id) for nm_id in nm_ids),
        }, safe=";")
        return f"{INTERNAL_CARDS_URL}?{query}"

    def _stock_cards_url(self, base: str, nm_ids: list[int], dest: int) -> str:
        # hide_dtype=13 is the warehouse-stock request Evirma sends. The price
        # request keeps hide_vflags and mtype, so SPP stays on the buyer query.
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

    def _parse_site_payload(self, payload: dict, offers: dict[int, dict[int, WbSiteOffer]]) -> int:
        added = 0
        for product in payload.get("products") or []:
            product_sizes = product.get("sizes") or []
            sizes = offers.setdefault(int(product["id"]), {})
            for size in product_sizes:
                option_id = size.get("optionId")
                if option_id is None:
                    continue
                product_price = (size.get("price") or {}).get("product")
                sizes[int(option_id)] = WbSiteOffer(
                    price=product_price / 100 if product_price is not None else None,
                    stock=None,
                )
                added += 1
        return added

    async def get_site_prices(self, nm_ids: list[int]) -> dict[int, dict[int, WbSiteOffer]]:
        """nm_id -> {optionId (= sizeID of the official API): buyer price and stock}.

        A size with no buyer price is still returned, so a missing SPP can be told
        apart from a storefront request that failed. Stock comes only from the
        multi-city warehouse scan.
        """
        offers = await self._get_site_prices_http(nm_ids)
        if offers:
            logger.info("WB site prices via HTTP: %s of %s nm_ids", len(offers), len(nm_ids))
            await self._attach_stock_http(nm_ids, offers)
            return offers
        logger.warning("HTTP got no WB site prices (card.wb.ru often returns 403), retrying via Chrome")
        offers = await self._get_site_prices_chrome(nm_ids)
        logger.info("WB site prices via Chrome: %s of %s nm_ids", len(offers), len(nm_ids))
        if not offers:
            logger.error("WB site prices empty — SPP and wallet columns will be blank")
        return offers

    async def _get_site_prices_http(self, nm_ids: list[int]) -> dict[int, dict[int, WbSiteOffer]]:
        offers: dict[int, dict[int, WbSiteOffer]] = {}
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
                self._parse_site_payload(payload, offers)
                await asyncio.sleep(REQUEST_PAUSE_SECONDS)
        return offers

    async def _attach_stock_http(self, nm_ids: list[int], offers: dict[int, dict[int, WbSiteOffer]]) -> None:
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
            await self._scan_warehouse_stock(nm_ids, offers, fetch_many, SITE_CARDS_URL)

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

    async def _scan_warehouse_stock(self, nm_ids, offers, fetch_many, base: str) -> None:
        # One request is one city. A wave sends STOCK_CONCURRENCY cities at once.
        # Any 429 holds the following wave; the limited requests go back in the queue.
        batches = [nm_ids[i:i + SITE_BATCH_SIZE] for i in range(0, len(nm_ids), SITE_BATCH_SIZE)]
        pending = [
            [dest, self._stock_cards_url(base, batch, dest), 0]
            for dest in STOCK_DESTS
            for batch in batches
        ]
        observations: list[tuple[int, int, int, int]] = []
        seen_products: set[int] = set()
        seen_sizes: set[tuple[int, int]] = set()
        first_dest = STOCK_DESTS[0]
        first_left = len(batches)
        first_ok = False
        limited = 0
        backoff = 1.0
        started = time.monotonic()
        logger.info(
            "loading WB warehouse stock for %s nm_ids across %s dests, %s at a time",
            len(nm_ids),
            len(STOCK_DESTS),
            STOCK_CONCURRENCY,
        )
        wave_no = 0
        while pending:
            wave_no += 1
            wave = pending[:STOCK_CONCURRENCY]
            pending = pending[STOCK_CONCURRENCY:]
            try:
                fetched = await fetch_many([url for _, url, _ in wave])
            except Exception:
                logger.warning("WB stock wave %s failed", wave_no, exc_info=True)
                fetched = [FetchResult(None, 0) for _ in wave]
            if len(fetched) != len(wave):
                fetched = list(fetched) + [FetchResult(None, 0)] * (len(wave) - len(fetched))
            retry = []
            retry_after = 0.0
            wave_ok = 0
            wave_limited = 0
            for (dest, url, attempt), result in zip(wave, fetched):
                if result.status == 429:
                    limited += 1
                    wave_limited += 1
                    if result.retry_after:
                        retry_after = max(retry_after, result.retry_after)
                    if attempt + 1 < STOCK_ATTEMPTS:
                        retry.append([dest, url, attempt + 1])
                    else:
                        logger.warning("WB stock dest=%s stayed rate limited", dest)
                        if dest == first_dest:
                            first_left -= 1
                    continue
                if not result.payload:
                    if dest == first_dest:
                        first_left -= 1
                    if result.status not in (0, 200):
                        logger.warning("WB stock dest=%s status=%s", dest, result.status)
                    continue
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
                logger.error("WB warehouse stock unavailable, site stock will be empty")
                return
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
            logger.error("WB warehouse stock empty, site stock will be empty")
            return
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

    async def _get_site_prices_chrome(self, nm_ids: list[int]) -> dict[int, dict[int, WbSiteOffer]]:
        # card.wb.ru stays 403. Prices come from the same-origin __internal/u-card
        # endpoint after the wbaas challenge, which headless Chrome does not finish.
        from playwright.async_api import async_playwright

        offers: dict[int, dict[int, WbSiteOffer]] = {}
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
                return offers
            session = await page.evaluate(
                """() => {
                    const hostVersion = window.__HOST_VERSION__;
                    return {
                        deviceid: localStorage.getItem('wbx__sessionID') || '',
                        spa: typeof hostVersion === 'string' ? hostVersion : '',
                    };
                }"""
            )
            # fixed, not the session geolocation: WB picks that by IP and it changed between runs
            dest = SITE_DEST
            deviceid = session.get("deviceid") or ""
            spa = session.get("spa") or ""
            logger.info(
                "WB storefront ready dest=%s spa=%s deviceid=%s",
                dest,
                spa or "missing",
                "yes" if deviceid else "no",
            )
            for i in range(0, len(nm_ids), SITE_BATCH_SIZE):
                batch = nm_ids[i:i + SITE_BATCH_SIZE]
                url = self._internal_cards_url(batch, dest)
                payload = await self._chrome_get_json(page, url, deviceid, spa)
                if payload is None:
                    continue
                added = self._parse_site_payload(payload, offers)
                logger.info(
                    "loaded WB site prices via Chrome, %s/%s nm_ids, %s sizes",
                    min(i + SITE_BATCH_SIZE, len(nm_ids)),
                    len(nm_ids),
                    added,
                )
                await asyncio.sleep(REQUEST_PAUSE_SECONDS)
            await self._scan_warehouse_stock(
                nm_ids,
                offers,
                lambda urls: self._chrome_fetch_many(page, urls, deviceid, spa),
                INTERNAL_CARDS_URL,
            )
        except Exception:
            logger.exception("Chrome fetch of WB site prices failed")
        finally:
            await browser.close()
            await pw.stop()
        return offers

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

    async def _chrome_get_json(self, page, url: str, deviceid: str, spa: str) -> dict | None:
        for attempt in range(4):
            fetched = await self._chrome_fetch_many(page, [url], deviceid, spa)
            result = fetched[0] if fetched else FetchResult(None, 0)
            if result.status == 429:
                delay = result.retry_after if result.retry_after else float(2 ** attempt)
                logger.warning("WB storefront rate limited, retry in %s s", delay)
                await asyncio.sleep(delay)
                continue
            if result.payload is None:
                return None
            return result.payload
        logger.warning("WB storefront stayed rate limited")
        return None

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
