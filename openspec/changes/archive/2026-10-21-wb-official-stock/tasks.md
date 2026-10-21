## 1. Остаток из API продавца

- [x] 1.1 В `src/api/wb_api.py` добавить константы URL складов, остатков FBS и `stocks-report/wb-warehouses`, а также `StockError` и `StockResult`. Проверка: `uv run python -c "import src.api.wb_api"` без ошибок.
- [x] 1.2 Реализовать FBS в `WbApi.get_stocks`: `GET /api/v3/warehouses`, затем `POST /api/v3/stocks/{id}` пачками по 1000 `chrtId` по всем складам, сумма `amount`, повтор на 429 по `X-Ratelimit-Retry`, ошибка с источником `fbs` и статусом. Проверка: `uv run python` на аккаунте `test`, артикул 180081238 — FBS по размерам 67, 36, 123, 17, 14, 6, 1, 5, 9, 2 или текущие значения, совпадающие с `stocks-report/seller-warehouses`.
- [x] 1.3 Реализовать FBO в `WbApi.get_stocks`: `POST stocks-report/wb-warehouses` пачками по 1000 `nmIds` с `offset`, пауза 20 с между запросами, 204 считается пустой пачкой, сумма `quantity` по `chrtId`. Если FBS или FBO не получен, `stocks = None`. Проверка: `uv run python` на `test` — FBO у 180081238 непустой и сумма FBS + FBO совпадает с пробным скриптом.
- [x] 1.4 Проверить ошибки: подменить токен на токен без «Аналитики» или передать заведомо неверный. Проверка: `stocks is None`, в `errors` источник и статус 401/403.

## 2. Витрина только для цены

- [x] 2.1 Удалить из `src/api/wb_api.py` `_stock_rows`, `_collect_stock_observations`, `SizeStock`, `aggregate_size_stock`, `merge_size_stock`, поля `stock` и `stock_capped` из `WbSiteOffer` и сбор наблюдений в `_scan_cities`. URL обхода не трогать. Проверка: `grep -n "stock" src/api/wb_api.py` находит только новый код остатков из API и `_stock_cards_url`, живой обход на `test` даёт те же средние цены, что и до правки.

## 3. Сервис, хранение и предупреждения

- [x] 3.1 В `WbService.collect_prices` запускать `get_stocks` и `get_site_prices` через `asyncio.gather`. `site_stock` брать из `StockResult` (0 для размера без строк при успехе, `None` при `stocks is None`), `site_stock_capped = 0` или `None`. Проверка: после сбора на `test` в `WbPrice` за сегодня у 180081238 остатки равны FBS + FBO, `site_stock_capped = 0`.
- [x] 3.2 Добавить тексты предупреждений об остатке по `design.md` и объединить их с `_site_warnings`. Убрать из текстов витрины упоминание остатка (`...SPP and stock are empty` → `...SPP are empty`). Проверка: сбор с токеном без «Аналитики» завершается `FINISHED`, в задаче метка «Warning» и текст про Personal token и Analytics, остаток в таблице «—».
- [x] 3.3 Обновить title колонок остатка в `templates/partials/wb_price.html`. Проверка в браузере: подсказка новая, старые дни с `>N` показываются с `>`.

## 4. Проверка и документация

- [x] 4.1 Живой сбор `uv run main.py` → «Collect now» на `test`: задача `FINISHED`, остатки 180081238 в таблице и Excel совпадают с FBS + FBO, цены и СПП такие же, как в сборе до изменения при том же наборе городов.
- [x] 4.2 Обновить `AGENTS.md`: строка про `src/wb_cities.py` — города только для цены. Добавить в Gotchas, что остаток WB берётся из Marketplace API и Аналитики и требует персонального токена с категориями «Маркетплейс» и «Аналитика». Поднять логируемую версию до 1.7.0. Проверка: `git diff AGENTS.md` и поиск версии.

## 5. Дополнения после проверки

- [x] 5.1 Повторять запросы витрины, оставшиеся без ответа (498, 5xx, сеть), после повторной проверки антибота в том же Chrome, до 2 кругов. Проверка: живой сбор на `test` — 18 городов с 498 ответили после одного круга, предупреждений нет.
- [x] 5.2 Набор городов по умолчанию — «7 regions», миграция `010_wb_cities_regions7.sql` переводит на него все аккаунты WB. Проверка: миграция на копии базы меняет `wb_dests:test` на 7 городов и не трогает другие параметры.
