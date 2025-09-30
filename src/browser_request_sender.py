from playwright.async_api import async_playwright
import json
import logging
import asyncio

from src.persistence.parameters_db import get_cookies

logger = logging.getLogger(__name__)

def on_console(msg):
    logger.info(f"browser console {msg.text}")

class BrowserRequestSender:

    def __init__(self, base_url: str):
        self.page = None
        self.pw = None
        self.browser = None
        self.base_url = base_url
        self.context = None
    async def init(self) -> "BrowserRequestSender":
        self.pw = await async_playwright().start()
        self.browser = await self.pw.chromium.launch(
            channel='chrome',
            headless=False,
            args=[
                '--disable-blink-features=AutomationControlled',
            ]
        )
        context = await self.browser.new_context()
        self.context = context
        converter = {
            "sameSite": lambda v: 'Strict' if v.lower().strip() == 'strict' else 'Lax' if v.lower().strip() == 'lax' else 'None',
            "partitionKey": lambda x: ""
        }
        cookies = await get_cookies()
        if not cookies:
            raise Exception("set cookies")
        cookies = json.loads(cookies.value)
        cookies = [{k: converter.get(k, lambda x: x)(v) for k, v in cookie.items()} for cookie in cookies]
        await context.add_cookies(cookies)
        self.page = await context.new_page()

        self.page.on('console', on_console)
        await self.page.goto(self.base_url)
        return self

    async def close(self):
        if self.page:
            await self.page.close()
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.pw:
            await self.pw.stop()

    async def send_request(self, method: str, url: str, payload: dict) -> dict:
        request_data = {
            'method': method,
            'url': url,
            'body': payload
        }
        response = await self.page.evaluate(
            #language=js
            """async (data) => {
                try {
                    const response = await fetch(data.url, {
                        method: data.method,
                        body: JSON.stringify(data.body)
                    });

                    if (!response.ok) {
                        const error = await response.text();
                        return { error: error, status: response.status };
                    }
                    return await response.json();
                } catch (error) {
                    return { error: error.toString() };
                }
            }""", request_data)

        if response and 'error' in response:
            raise Exception(response.get('error'))

        return response

async def main():
    payload = {
        "company_id": "836045",
        "item_ids": [
            "2361753137"
        ]
    }
    br = BrowserRequestSender("https://seller.ozon.ru/app/reviews")
    await br.init()
    res = await br.send_request("POST", "https://seller.ozon.ru/api/pricing-bff-service/v3/get-common-prices", payload)
    print(f"res 1 {res}")
    res = await br.send_request("POST", "https://seller.ozon.ru/api/pricing-bff-service/v3/get-common-prices", payload)
    print(f"res 2 {res}")
    input()

if __name__ == '__main__':
    asyncio.run(main())