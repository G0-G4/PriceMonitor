CREATE TABLE IF NOT EXISTS WbPrice
(
    account TEXT, -- идентификатор кабинета WB
    nm_id INTEGER, -- артикул WB
    vendor_code TEXT, -- артикул продавца
    size_id INTEGER, -- id размера
    tech_size_name TEXT, -- размер
    name TEXT, -- название из Content API
    date DATE, -- дата получения цены
    price DOUBLE, -- базовая цена
    discounted_price DOUBLE, -- цена со скидкой продавца
    club_discounted_price DOUBLE, -- цена с скидкой WB Клуба
    discount INTEGER, -- скидка продавца, %
    club_discount INTEGER, -- скидка WB Клуба, %
    wb_discount INTEGER, -- скидка WB на сайте (discountOnSite), %
    PRIMARY KEY (account, nm_id, size_id, date)
);

CREATE INDEX idx_wb_price_vendor_code ON WbPrice (vendor_code);
CREATE INDEX idx_wb_price_date ON WbPrice (date);
CREATE INDEX idx_wb_price_nm_id ON WbPrice (nm_id);
