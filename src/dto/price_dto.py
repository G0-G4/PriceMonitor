import logging
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)

class ByDeliverySchema(BaseModel):
    delivery_schema: str
    in_stock: bool
    marketing_price: float
    marketing_oa_price: float
    marketing_seller_price: float

class Price(BaseModel):
    item_id: str
    currency_code: str
    price: float
    old_price: float
    marketing_price: float
    marketing_oa_price: float
    marketing_seller_price: float
    by_delivery_schema: list[ByDeliverySchema] = []

    def get_marketing_price(self) -> float | None:
        for ds in ("FBO", "FBS", "RFBS"):
            for schema in self.by_delivery_schema:
                if schema.delivery_schema == ds and schema.in_stock:
                    return schema.marketing_price
        logger.warning(f"no in-stock delivery schema found for marketing_price, item_id={self.item_id}")
        return None

    def get_marketing_oa_price(self) -> float | None:
        for ds in ("FBO", "FBS", "RFBS"):
            for schema in self.by_delivery_schema:
                if schema.delivery_schema == ds and schema.in_stock:
                    return schema.marketing_oa_price
        logger.warning(f"no in-stock delivery schema found for marketing_oa_price, item_id={self.item_id}")
        return None

class PriceResponse(BaseModel):
    items: list[Price]
    errors: list[Any]
