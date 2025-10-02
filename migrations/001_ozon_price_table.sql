CREATE TABLE IF NOT EXISTS OzonPrice
(
    company_id TEXT, -- id компании ozon
    item_id TEXT, -- id товара ozon
    offer_id TEXT, --  один из id товаров
    date DATE, -- дата получения цены
    name TEXT,
    marketing_seller_price DOUBLE, -- цена продажи
    old_price DOUBLE, -- зачеркнутая цена на карточке товара
    marketing_price DOUBLE, -- цена с картой озона
    marketing_oa_price DOUBLE, -- СПП
    PRIMARY KEY (offer_id, date, company_id)
);

CREATE INDEX idx_ozon_price_item_id ON OzonPrice (item_id);
CREATE INDEX idx_ozon_price_offer_id ON OzonPrice (offer_id);
CREATE INDEX idx_ozon_price_date ON OzonPrice (date);
