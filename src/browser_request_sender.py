from playwright.async_api import async_playwright
import asyncio
import logging
import os

from src.config import BROWSER_STARTUP_SLEEP_SECONDS, HEADLESS_BROWSER, SUSPEND_AFTER_BROWSER_STARTUP, USER_DATA_DIR

logger = logging.getLogger(__name__)

LOGIN_TIMEOUT_SECONDS = 600


def on_console(msg):
    logger.info(f"browser console {msg.text}")


class BrowserRequestSender:

    def __init__(self, base_url: str):
        self.page = None
        self.pw = None
        self.context = None
        self.base_url = base_url

    async def init(self) -> "BrowserRequestSender":
        os.makedirs(USER_DATA_DIR, exist_ok=True)
        self.pw = await async_playwright().start()
        self.context = await self.pw.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            channel='chrome',
            headless=HEADLESS_BROWSER,
            args=[
                '--disable-blink-features=AutomationControlled',
            ]
        )
        self.page = await self.context.new_page()
        self.page.on('console', on_console)
        await self.page.goto(self.base_url)
        await asyncio.sleep(BROWSER_STARTUP_SLEEP_SECONDS)
        if SUSPEND_AFTER_BROWSER_STARTUP:
            input("suspend after browser startup. Enter anything to continue")
        return self

    async def close(self):
        # page is closed implicitly when context closes
        if self.context:
            try:
                await self.context.close()
            except Exception:
                pass
        if self.pw:
            try:
                await self.pw.stop()
            except Exception:
                pass
        self.page = None
        self.context = None
        self.pw = None

    async def send_request(self, method: str, url: str, payload: dict) -> dict:
        request_data = {
            'method': method,
            'url': url,
            'body': payload
        }
        if self.page is None:
            raise Exception("browser is not initialized")
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
            status = response.get('status')
            if status in (401, 403):
                raise ReLoginRequiredError(response.get('error'))
            raise Exception(response.get('error'))

        return response

    async def login(self) -> bool:
        os.makedirs(USER_DATA_DIR, exist_ok=True)
        self.pw = await async_playwright().start()
        self.context = await self.pw.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            channel='chrome',
            headless=False,
            args=[
                '--disable-blink-features=AutomationControlled',
            ]
        )
        page = await self.context.new_page()
        page.on('console', on_console)

        markers = {"closed": False}

        def on_close():
            markers["closed"] = True

        page.on("close", on_close)

        try:
            await page.goto("https://seller.ozon.ru/")
        except Exception:
            logger.debug("initial goto failed, waiting for user login", exc_info=True)

        deadline = asyncio.get_event_loop().time() + LOGIN_TIMEOUT_SECONDS
        timed_out = False
        try:
            while not markers["closed"]:
                if asyncio.get_event_loop().time() > deadline:
                    logger.warning("login timed out after %s seconds", LOGIN_TIMEOUT_SECONDS)
                    timed_out = True
                    break
                await asyncio.sleep(1.0)
        finally:
            try:
                if not page.is_closed():
                    await page.close()
            except Exception:
                pass
            try:
                await self.context.close()
            except Exception:
                pass
            try:
                await self.pw.stop()
            except Exception:
                pass
            self.page = None
            self.context = None
            self.pw = None

        return not timed_out


def profile_exists() -> bool:
    if not USER_DATA_DIR or not os.path.isdir(USER_DATA_DIR):
        return False
    return os.path.isdir(os.path.join(USER_DATA_DIR, "Default")) or os.path.isfile(os.path.join(USER_DATA_DIR, "Local State"))


class ReLoginRequiredError(Exception):
    pass


async def main():
    br = BrowserRequestSender("https://seller.ozon.ru/app/reviews")
    await br.init()
    res = await br.send_request("POST", "https://seller.ozon.ru/api/pricing-bff-service/v3/get-common-prices", {
        "company_id": "836045",
        "item_ids": ["2361753137"]
    })
    print(f"res 1 {res}")
    await br.close()


if __name__ == '__main__':
    asyncio.run(main())