import http.client
import json
import sys
import logging.handlers
import time
import ssl

log_filename = f"test.log"

root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)

formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(filename)s - %(lineno)d - %(message)s')

# File handler
file_handler = logging.handlers.RotatingFileHandler(
    log_filename,
    backupCount=3,
    maxBytes=5_000_000
)
file_handler.setFormatter(formatter)

# Console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)

root_logger.handlers = []
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

logger = logging.getLogger(__name__)

payload = {
    "company_id": "836045",
    "item_ids": [
        "2361753137"
    ]
}



from playwright.sync_api import sync_playwright

def make_request(page, url, method, payload):
    request_data = {
        'method': method,
        'url': url,
        'body': payload
    }
    response = page.evaluate(
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
        

def main():
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(
        channel='chrome',
        headless=False,
        args=[
            '--disable-blink-features=AutomationControlled',
        ]
    )
    context = browser.new_context()
    converter = {
        "sameSite": lambda v: 'Strict' if v.lower().strip() == 'strict' else 'Lax' if v.lower().strip() == 'lax' else 'None',
        "partitionKey": lambda x: ""
    }
    with open("cookies.json") as f:
        cookies = json.load(f)
    cookies = [{k: converter.get(k, lambda x: x)(v) for k, v in cookie.items()} for cookie in cookies]
    context.add_cookies(cookies)
    page = context.new_page()
    def on_console(msg):
        logger.info(f"browser console {msg.text}")
    page.on('console', on_console)
    page.goto("https://seller.ozon.ru/app/reviews")
    time.sleep(3)
    response = make_request(page, "https://seller.ozon.ru/api/pricing-bff-service/v3/get-common-prices", 'POST', payload)
    print(f"Response: {response}")
    input()

if __name__ == '__main__':
    main()
