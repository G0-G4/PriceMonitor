"""Rebuild data/wb_cities.json: Russian cities with WB pickup points and one dest per city.

Run by hand, the app never downloads this:
    uv run python scripts/build_wb_cities.py [all-poo-fr-vN.json]

The pickup-point list is about 30 MB and WB sometimes serves it slowly. A file
already downloaded from POO_URL can be passed instead.

Sources: the WB pickup-point list the storefront uses (every point carries its dest)
and hflabs/city (district, region, population, centre coordinates, CC BY 4.0).
A city takes the dest of the pickup point nearest its centre. Cities from Evirma's
lists keep Evirma's dest so the presets match Evirma exactly.
"""
import collections
import csv
import io
import json
import math
import os
import re
import sys
import urllib.request

POO_URL = "https://static-basket-01.wbbasket.ru/vol0/data/all-poo-fr-v{}.json"
CITY_URL = "https://raw.githubusercontent.com/hflabs/city/master/city.csv"
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "wb_cities.json")
MAX_DISTANCE_KM = 60

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.wb_cities import EVIRMA_POINTS  # noqa: E402

FOREIGN_CITIES = {"Минск": "Беларусь", "Астана": "Казахстан"}
# Evirma's dest wins over the nearest pickup point, so the presets match Evirma
PINNED = {name: dest for name, dest in EVIRMA_POINTS.items() if name not in FOREIGN_CITIES}
FOREIGN = [
    {"city": "Минск", "region": FOREIGN_CITIES["Минск"], "district": "Другие страны", "population": 1995471, "dest": EVIRMA_POINTS["Минск"]},
    {"city": "Астана", "region": FOREIGN_CITIES["Астана"], "district": "Другие страны", "population": 1423726, "dest": EVIRMA_POINTS["Астана"]},
]
DISTRICT_ORDER = [
    "Центральный", "Северо-Западный", "Южный", "Северо-Кавказский", "Приволжский",
    "Уральский", "Сибирский", "Дальневосточный", "Другие страны",
]
CITY_PART = re.compile(r"^(?:г\.?\s*|город\s+)?([А-Яа-яЁё\- ]+)$")


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=600) as resp:
        return resp.read()


def russian_points(data: list) -> list[dict]:
    return [item for country in data if country["country"] == "ru" for item in country["items"] if item.get("dest")]


def latest_pickup_points() -> list[dict]:
    # The version number grows over time. Take the newest one that downloads in full.
    for version in range(30, 0, -1):
        try:
            data = json.loads(fetch(POO_URL.format(version)))
        except Exception:
            continue
        print(f"pickup points v{version}", file=sys.stderr)
        return russian_points(data)
    raise SystemExit("no WB pickup-point list downloaded")


def norm(name: str) -> str:
    return name.lower().replace("ё", "е").strip()


def distance_km(a, b) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def region_label(row: dict) -> str:
    # Moscow, Saint Petersburg and Sevastopol are regions themselves
    if row["region_type"] == "г":
        return row["region"]
    return f'{row["region"]} {row["region_type"]}'


def main():
    cities = list(csv.DictReader(io.StringIO(fetch(CITY_URL).decode("utf-8"))))
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as f:
            points = russian_points(json.load(f))
    else:
        points = latest_pickup_points()
    by_name = collections.defaultdict(list)
    for row in cities:
        by_name[norm(row["city"] or row["region"])].append(row)

    city_points = collections.defaultdict(list)
    for point in points:
        for part in [p.strip() for p in point["address"].split(",")][:3]:
            match = CITY_PART.match(part)
            candidates = by_name.get(norm(match.group(1))) if match else None
            if not candidates:
                continue
            # same-name towns in different regions: the nearest one
            row = min(candidates, key=lambda c: distance_km(point["coordinates"], (float(c["geo_lat"]), float(c["geo_lon"]))))
            if distance_km(point["coordinates"], (float(row["geo_lat"]), float(row["geo_lon"]))) <= MAX_DISTANCE_KM:
                city_points[row["kladr_id"]].append(point)
            break

    result = []
    for row in cities:
        name = row["city"] or row["region"]
        found = city_points.get(row["kladr_id"])
        dest = PINNED.get(name)
        if dest is None:
            if not found:
                continue
            centre = (float(row["geo_lat"]), float(row["geo_lon"]))
            dest = min(found, key=lambda p: distance_km(p["coordinates"], centre))["dest"]
        result.append({
            "city": name,
            "region": region_label(row),
            "district": row["federal_district"],
            "population": int(row["population"] or 0),
            "dest": dest,
        })
    result.extend(FOREIGN)

    missing = set(PINNED) - {item["city"] for item in result}
    if missing:
        raise SystemExit(f"pinned cities not in hflabs/city: {sorted(missing)}")
    dests = collections.Counter(item["dest"] for item in result)
    duplicates = [item["city"] for item in result if dests[item["dest"]] > 1]
    if duplicates:
        print(f"cities sharing a dest: {duplicates}", file=sys.stderr)

    result.sort(key=lambda item: (DISTRICT_ORDER.index(item["district"]), item["region"], -item["population"]))
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    print(f"{len(result)} cities, {len(points)} pickup points", file=sys.stderr)


if __name__ == "__main__":
    main()
