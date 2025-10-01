from typing import Any

from pydantic import BaseModel

class PartItem(BaseModel):
   offer_id: str
   name: str
class Item(BaseModel):
    item_id: str
    company_id: str
    part_item: PartItem

class ItemResponse(BaseModel):
    products: list[Item]
    cursor: str
    total_items: int
    provider_errors: list[Any]
