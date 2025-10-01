from typing import Any

from pydantic import BaseModel

class Price(BaseModel):
    item_id: str
    currency_code: str
    price: float
    old_price: float
    marketing_price: float
    marketing_oa_price: float
    marketing_seller_price: float

class PriceResponse(BaseModel):
    items: list[Price]
    errors: list[Any]
