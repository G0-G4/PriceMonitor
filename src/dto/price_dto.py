import logging
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator

logger = logging.getLogger(__name__)


def empty_str_to_none(value: Any) -> Any:
    if value == "":
        return None
    return value


OptionalFloat = Annotated[float | None, BeforeValidator(empty_str_to_none)]


class ByDeliverySchema(BaseModel):
    delivery_schema: str
    in_stock: bool
    marketing_price: OptionalFloat = None
    marketing_oa_price: OptionalFloat = None
    marketing_seller_price: OptionalFloat = None

class Price(BaseModel):
    item_id: str
    currency_code: str
    price: OptionalFloat = None
    old_price: OptionalFloat = None
    marketing_price: OptionalFloat = None
    marketing_oa_price: OptionalFloat = None
    marketing_seller_price: OptionalFloat = None
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
