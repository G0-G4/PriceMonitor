import asyncio
import logging
from decimal import Decimal, ROUND_FLOOR

import aiohttp

from src.config import WB_WALLET_LEVEL, WB_WALLET_REFRESH_MINUTES

logger = logging.getLogger(__name__)

DEFAULT_PAYMENT_URL = "https://static-basket-01.wbbasket.ru/vol1/global-payment/default-payment.json"

WC_TYPE_UNLOGGED = "Незалогиненный кошелёк"
WC_TYPE_ANONYMOUS = "ВБ Клуб Аноним кошелёк"

_LEVEL_TO_WC_TYPE = {
    "anonymous": WC_TYPE_ANONYMOUS,
    "anon": WC_TYPE_ANONYMOUS,
    "аноним": WC_TYPE_ANONYMOUS,
    "unlogged": WC_TYPE_UNLOGGED,
    "незалогиненный": WC_TYPE_UNLOGGED,
}

_rates: dict[str, float] = {}
_lock = asyncio.Lock()


def selected_wc_type() -> str:
    key = (WB_WALLET_LEVEL or "anonymous").strip().lower()
    return _LEVEL_TO_WC_TYPE.get(key, WC_TYPE_ANONYMOUS)


def parse_payment_rates(payload: dict) -> dict[str, float]:
    rates: dict[str, float] = {}
    if payload.get("state") not in (0, None):
        return rates
    for item in payload.get("data") or []:
        if not item.get("is_active"):
            continue
        wc_type = item.get("wc_type")
        try:
            discount = float(item["discount_value"])
        except (KeyError, TypeError, ValueError):
            continue
        if wc_type:
            rates[wc_type] = discount
    return rates


def wallet_price_from_spp(spp: float | None, percent: float | None = None) -> float | None:
    if spp is None:
        return None
    if percent is None:
        percent = selected_percent()
    if percent is None:
        return None
    discounted = (
        Decimal(str(spp)) * (Decimal("100") - Decimal(str(percent))) / Decimal("100")
    ).quantize(Decimal("1"), rounding=ROUND_FLOOR)
    return float(discounted)


def selected_percent() -> float | None:
    return _rates.get(selected_wc_type())


async def refresh_wallet_discounts() -> dict[str, float]:
    timeout = aiohttp.ClientTimeout(total=30)
    headers = {"User-Agent": "Mozilla/5.0"}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        async with session.get(DEFAULT_PAYMENT_URL) as resp:
            resp.raise_for_status()
            payload = await resp.json()
    rates = parse_payment_rates(payload)
    if not rates:
        raise ValueError("default-payment.json has no active wallet discounts")
    async with _lock:
        _rates.clear()
        _rates.update(rates)
    wc_type = selected_wc_type()
    percent = rates.get(wc_type)
    logger.info(
        "WB wallet discounts %s, using %s = %s%%",
        rates,
        wc_type,
        percent,
    )
    if percent is None:
        logger.warning("configured WB_WALLET_LEVEL maps to %s, missing from %s", wc_type, rates)
    return dict(_rates)


async def run_wallet_discount_loop():
    interval = WB_WALLET_REFRESH_MINUTES * 60
    while True:
        await asyncio.sleep(interval)
        try:
            await refresh_wallet_discounts()
        except Exception:
            logger.exception("failed to refresh WB wallet discounts")
