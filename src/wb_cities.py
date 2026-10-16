"""Cities a WB account can collect buyer prices and stock in.

data/wb_cities.json is built by scripts/build_wb_cities.py from the WB pickup-point
list: one dest per city. SPP is the same in every delivery zone of a city, so any
zone of it gives the city's price.
"""
import hashlib
import json
import logging
from dataclasses import dataclass
from functools import cache

logger = logging.getLogger(__name__)

CITIES_PATH = "data/wb_cities.json"
MAX_CITIES = 100

# Evirma 2.60.2 seo points, in Evirma's order. Moscow is the SPP point -1257786,
# Evirma's stock point -364001 shows the same warehouses and SPP.
EVIRMA_POINTS: dict[str, int] = {
    "Москва": -1257786,
    "Балашиха": 123586098,
    "Смоленск": -3339991,
    "Тверь": -1263279,
    "Рязань": -5817685,
    "Воронеж": 12358385,
    "Ярославль": -3351953,
    "Санкт-Петербург": -1187265,
    "Тольятти": -2448021,
    "Саратов": 12358461,
    "Самара": -1257218,
    "Уфа": 12358495,
    "Казань": -2133462,
    "Новокузнецк": -2689194,
    "Нижний Новгород": 12358535,
    "Пермь": 12358361,
    "Волгоград": -4039466,
    "Ростов-на-Дону": -2228364,
    "Краснодар": 12358058,
    "Махачкала": -5921133,
    "Грозный": -3888337,
    "Магнитогорск": 123585969,
    "Тюмень": -897988,
    "Челябинск": -1579833,
    "Екатеринбург": -5803327,
    "Омск": -3902910,
    "Новосибирск": -364763,
    "Красноярск": 12356481,
    "Хабаровск": -1785058,
    "Владивосток": 123586013,
    "Иркутск": -5827722,
    "Минск": -59208,
    "Астана": 85,
}
MOSCOW = (-1257786,)
EVIRMA_33 = tuple(EVIRMA_POINTS.values())
# the cities of Evirma's "СПП по регионам" export
REGIONS_7 = tuple(EVIRMA_POINTS[name] for name in (
    "Москва", "Санкт-Петербург", "Краснодар", "Казань", "Екатеринбург", "Новосибирск", "Хабаровск",
))
PRESETS: dict[str, tuple[int, ...]] = {
    "evirma": EVIRMA_33,
    "regions7": REGIONS_7,
    "moscow": MOSCOW,
}


@dataclass(frozen=True)
class WbCity:
    city: str
    region: str
    district: str
    population: int
    dest: int


@cache
def all_cities() -> tuple[WbCity, ...]:
    with open(CITIES_PATH, encoding="utf-8") as f:
        return tuple(WbCity(**item) for item in json.load(f))


@cache
def _by_dest() -> dict[int, WbCity]:
    # a few small towns share a dest with a neighbour, the larger one names it
    result: dict[int, WbCity] = {}
    for city in sorted(all_cities(), key=lambda c: c.population):
        result[city.dest] = city
    return result


def city_name(dest: int) -> str:
    """Name for warnings. A dest dropped from a rebuilt directory still works on WB."""
    city = _by_dest().get(dest)
    return city.city if city else str(dest)


def dests_key(dests) -> str:
    """Fingerprint of the cities a price was averaged over, independent of their order."""
    joined = ",".join(str(dest) for dest in sorted(set(dests)))
    return hashlib.sha1(joined.encode()).hexdigest()[:12]
