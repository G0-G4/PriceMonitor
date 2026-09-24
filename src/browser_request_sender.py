from playwright.async_api import async_playwright
import asyncio
import json
import logging
import os

from src.config import BROWSER_STARTUP_SLEEP_SECONDS, HEADLESS_BROWSER, SUSPEND_AFTER_BROWSER_STARTUP, USER_DATA_DIR

logger = logging.getLogger(__name__)

LOGIN_TIMEOUT_SECONDS = 600


def on_console(msg):
    logger.info(f"browser console {msg.text}")


class BrowserRequestSender:

    def __init__(self, base_url: str, user_data_dir: str | None = None, login_url: str | None = None):
        self.page = None
        self.pw = None
        self.context = None
        self.base_url = base_url
        self.user_data_dir = user_data_dir or USER_DATA_DIR
        self.login_url = login_url or "https://seller.ozon.ru/"

    async def init(self) -> "BrowserRequestSender":
        if self.page is not None:
            return self
        os.makedirs(self.user_data_dir, exist_ok=True)
        self.pw = await async_playwright().start()
        self.context = await self.pw.chromium.launch_persistent_context(
            user_data_dir=self.user_data_dir,
            channel='chrome',
            headless=HEADLESS_BROWSER,
            args=[
                '--disable-blink-features=AutomationControlled',
            ]
        )
        self.page = await self.context.new_page()
        self.page.on('console', on_console)
        await self._goto_with_retry(self.base_url)
        await asyncio.sleep(BROWSER_STARTUP_SLEEP_SECONDS)
        if SUSPEND_AFTER_BROWSER_STARTUP:
            input("suspend after browser startup. Enter anything to continue")
        return self

    async def _goto_with_retry(self, url: str, attempts: int = 3) -> None:
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                await self.page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                return
            except Exception as e:
                last_error = e
                logger.warning("goto %s failed (attempt %s/%s): %s", url, attempt, attempts, e)
                if attempt < attempts:
                    await asyncio.sleep(2 ** attempt)
        assert last_error is not None
        raise last_error

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

    async def send_context_request(self, method: str, url: str, payload: dict | None = None, extra_headers: dict | None = None) -> dict:
        if self.context is None:
            raise Exception("browser is not initialized")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)
        kwargs = {"headers": headers, "timeout": 60_000}
        if payload is not None:
            kwargs["data"] = json.dumps(payload)

        if method.upper() == "POST":
            response = await self.context.request.post(url, **kwargs)
        elif method.upper() == "GET":
            response = await self.context.request.get(url, **kwargs)
        else:
            raise ValueError(f"unsupported method {method}")

        status = response.status
        text = await response.text()
        if status in (401, 403):
            raise ReLoginRequiredError(text)
        if status >= 400:
            raise Exception(f"request failed {status}: {text[:500]}")
        if not text:
            return {}
        return json.loads(text)

    async def get_local_storage(self) -> dict[str, str]:
        if self.page is None:
            return {}
        try:
            storage = await self.page.evaluate(
                """() => {
                    const out = {};
                    for (let i = 0; i < localStorage.length; i++) {
                        const key = localStorage.key(i);
                        out[key] = localStorage.getItem(key);
                    }
                    return out;
                }"""
            )
            return storage or {}
        except Exception:
            logger.exception("failed to read localStorage")
            return {}

    async def login(self) -> bool:
        os.makedirs(self.user_data_dir, exist_ok=True)
        self.pw = await async_playwright().start()
        self.context = await self.pw.chromium.launch_persistent_context(
            user_data_dir=self.user_data_dir,
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
            await page.goto(self.login_url)
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


def profile_exists(user_data_dir: str | None = None) -> bool:
    directory = user_data_dir or USER_DATA_DIR
    if not directory or not os.path.isdir(directory):
        return False
    return os.path.isdir(os.path.join(directory, "Default")) or os.path.isfile(os.path.join(directory, "Local State"))


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