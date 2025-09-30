import asyncio

from src.browser_request_sender import BrowserRequestSender
from src.dto.item_dto import ItemResponse
from src.dto.price_dto import PriceResponse
import logging

logger = logging.getLogger(__name__)

class OzonApi:
    def __init__(self, request_sender):
        self.request_sender: BrowserRequestSender = request_sender

    async def get_common_prices(self, compandy_id: str, item_ids: list[str]) -> PriceResponse:
        url = "https://seller.ozon.ru/api/pricing-bff-service/v3/get-common-prices"
        payload = {
            "company_id": compandy_id,
            "item_ids": item_ids
        }
        response = await self.request_sender.send_request("POST", url, payload)
        logger.debug(response)
        return PriceResponse.model_validate(response)
    async def list_by_filter(self, company_id: str, search:str = "", limit:int = 50, offset: int = 0) -> ItemResponse:
        url = "https://seller.ozon.ru/api/v1/products/list-by-filter"
        payload = {
            "company_id": company_id,
            "filters": {
                "search": search,
                "categories": []
            },
            "aggregate": {
                "parts": [
                    "PART_ITEM",
                ],
                "attribute_ids": [
                    "4194",
                    "8229"
                ],
                "human_texts": True
            },
            "return_total_items": True,
            "visibility": "ALL",
            "sort_by": "SORT_BY_CREATED_AT",
            "sort_dir": "SORT_DIRECTION_DESC",
            "limit": limit,
            "offset": offset
        }
        response = await self.request_sender.send_request("POST", url, payload)
        logger.debug(response)
        return ItemResponse.model_validate(response)

    async def open_browser(self):
        await self.request_sender.init()

    async def close_browser(self):
        await self.request_sender.close()

async def main():
    sender = await BrowserRequestSender("https://seller.ozon.ru/app/reviews").init()
    api = OzonApi(sender)
    res = await api.get_common_prices("836045", ["2361753137"])
    print(res)
    res = await api.list_by_filter("1104328")
    print(res)
    res = await api.list_by_filter("1104328", offset=len(res.products))
    print(res)

if __name__ == '__main__':
    asyncio.run(main())