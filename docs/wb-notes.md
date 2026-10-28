# Wildberries notes

Facts about WB APIs and the storefront that the code relies on, with the date they were checked.

## Stock comes from the seller API (checked 2026-10-21)

A client reported missing FBS stock. The anonymous storefront (`__internal/u-card/cards/v4/detail`)
does return FBS warehouses (`dtype & 7` = FBS, `& 8` = FBO), but the city scan misses whole seller
warehouses: one with 93 units never showed. Small quantities like 5 were real: the seller sets 5 on
several FBS warehouses. `hide_dtype` changes nothing. Per-size stock as third-party analytics tools
show it comes from one authenticated buyer request to `__internal/card/cards/v4/detail`.

Since change `wb-official-stock`, stock = Marketplace FBS + Analytics `wb-warehouses`. FBS+FBO
matched a third-party tool for 7 of 10 sizes.

Official methods (docs as of 2026-10-20; dev.wildberries.ru returns 498 to curl, open it in
Playwright Chrome):

- FBS: `GET marketplace-api.wildberries.ru/api/v3/warehouses`, then `POST /api/v3/stocks/{warehouseId}`
  with `{"chrtIds": [...]}` (up to 1000) → `{stocks: [{chrtId, amount}]}`. Category Маркетплейс,
  any token type, 300/min.
- WB warehouses: `POST seller-analytics-api.wildberries.ru/api/analytics/v1/stocks-report/wb-warehouses`
  (nmIds ≤ 1000; rows nmId/chrtId/warehouseId/quantity/inWayToClient/inWayFromClient). Refreshes every
  30 min, 3/min. Personal, Service, or Basic-with-secret token only. Returns one aggregated
  "Склад WB" row per size.
- Seller warehouses: `.../stocks-report/seller-warehouses`, Personal or Service token only. Its FBS sum
  equals the Marketplace API exactly.
- Fallback for a Basic token: the `warehouse_remains` task report (Basic: 4/hour).
- `statistics-api /api/v1/supplier/stocks` no longer appears in the docs.
- Token type is the JWT payload `acc` field: 1 Basic, 3 Personal, 4 Service.

`chrtId` == our `size_id` == prices API `sizeID` == storefront `optionId` (verified with a Personal
token). Before relying on the Analytics methods, check the client's token type and categories.

## Buyer price depends on the serving warehouse (checked 2026-10-28)

A client reported the site showing a price ~1.6× higher than the report. The parser was right:

- The storefront `spp` query param changes nothing (`spp=30`, `spp=0`, absent — same price).
- In Moscow an anonymous and a logged-in buyer saw the same price.
- The anonymous price differs by city by a few percent across the 7-region preset (SPP 37–39%).
- Near the seller's express warehouse (`/api/v3/warehouses` entry with `deliveryType` 6; ordinary
  FBS is `deliveryType` 1) sizes stocked there are sold as "курьер продавца, за 3 часа". That offer
  has a different `saleConditions` and no SPP: the buyer price equals the seller's `discountedPrice`.
  The courier zone covered the warehouse's city and two towns ~30 km away; no other city in five
  neighbouring regions got it. Sizes served from other warehouses in the same city keep the normal
  price, and which sizes get the courier offer changed between two runs on the same day.

So the report averages the cabinet's cities, and a buyer near a seller express warehouse sees a much
higher price. When a client reports a higher site price, ask for their delivery city and check the
cabinet for `deliveryType` 6 warehouses before suspecting the parser. Pricing a cabinet in such a
city alone shows that price, and the SPP column then holds the seller price (SPP 0%), but a size
flips between the two prices as its stock on the express warehouse runs out or is restocked.
