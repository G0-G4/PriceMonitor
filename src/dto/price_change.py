
from datetime import date
from pydantic import BaseModel

class PriceChange(BaseModel):
    date: date
    company_id: str
    offer_id: str
    name: str
    today_seller_price: float | None
    today_spp: float | None
    today_ozon_card: float | None
    yesterday_seller_price: float | None
    yesterday_spp: float | None
    yesterday_ozon_card: float | None

class PriceChangeResponse(BaseModel):
    price_changes: list[PriceChange]
    total: int