-- остаток размера на витрине WB (сумма stocks[].qty), NULL если витрина не ответила по этому размеру
ALTER TABLE WbPrice ADD COLUMN site_stock INTEGER
