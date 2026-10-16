-- 1 when the stored site_stock is a lower bound because WB clipped qty. UI and Excel show >N
ALTER TABLE WbPrice ADD COLUMN site_stock_capped INTEGER
