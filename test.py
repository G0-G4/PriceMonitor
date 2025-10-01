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

payload = json.dumps({
    "company_id": "836045",
    "item_ids": [
        "2361753137"
    ]
})
headers = {
    'accept': 'application/json, text/plain, */*',
    'accept-language': 'ru',
    'cache-control': 'no-cache',
    'content-type': 'application/json',
    'origin': 'https://seller.ozon.ru',
    'pragma': 'no-cache',
    'priority': 'u=1, i',
    'referer': 'https://seller.ozon.ru/app/prices/control?search=135973',
    'sec-ch-ua': '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"macOS"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-origin',
    'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
    'x-o3-app-name': 'seller-ui',
    'x-o3-company-id': '836045',
    'x-o3-language': 'ru',
    'x-o3-page-type': 'prices',
    'Cookie': '__Secure-ab-group=92; abt_data=7.BC2e76Kj1F1ROcUKXqwBnnZHqzBY7Stq88UI_2DPuLp-qIQX9GuBoSjqHGsD1EdRsM8B0VQf5ctnkfEr5ExfnNVKzhOXn07ox-2pzfO2AZIUrqhKdPpLfsXitmGNcg2yS1MgId2rqTRlkhqntzWtDQXqWpnWaAXNQpH27Pvxw8ZbAOecROPkv7oyjgxtEjbe3pWrzeeT-XxlIfatYYg9-bSSyr4u7mjk_QucX75JYeOBBEPe1HJYARCuuL8XSxxwduHIWgsVTGgLMRS_inADoNXVQ1TE9i0WZNTNLlEmkhtzsAMe5J-EykWgLMQXFNVa_Zt2iXcghjYo9vsgTDQOdC0mfVpJslo7lGqOaoU4rWQDDX4wq0Vzk1d_KWu9q9lSgj-IBlQ57XE1htE3quom3yn4QeXvhdPp5ykxzVnb1Bom_C0gblVbbbsF-jjxpJiUrkoCZddWvOFV23Eq-2fknCEgvEP_0seP2cYFKDGJQcfjKOCzvART70N3k8uHjZ8o_Ge5wLsc7ZI-6OsZeyQR2rM4kkauwuWYpgTjYeZVzDZouI1AqGtf9js5KGc; __Secure-ext_xcid=ea303c56d202ba56edca1f24c56db1d7; sc_company_id=836045; xcid=83d2a50685bc2218dc1c047f68da9492; __Secure-sid=sc1.a8li8rRbQOOY4BelAgeUZg.AQpFdmpWw_SsKK0zb1aPTS9APgBM9ARGcCWa1tK8pFn1__a4bf3oZytWLq1N3ri4kfdrUmrqJpCKaqErRIlCJ1Q.cKT3OF1knYVASUoSWjS8lgtmqXk9Moh6hThCMHgnBoU.1ffbac63696544af5; is_adult_confirmed=; is_alco_adult_confirmed=; __Secure-user-id=99058575; bacntid=1517836; x-o3-language=ru; ADDRESSBOOKBAR_WEB_CLARIFICATION=1759178529; __Secure-ETC=00bd5c0690f55ecfa38dc14532716768; abt_data=7.vajoklYb4r2gl8jzSNY2EVFjLv-mQWPFvcHThFXaSPx8rLWYtKSLJCvjsSW1wAMiKxeYEnscZbe7u6W1-bEkToWg1zaSvoGFzkR2x7JIIz7Eh8ibCo55Fm-aM-PFf1I8Z1oR8Hgbx3eLEmUxqV1q1ioK7lGJFK_9LtonU875LojDN32Xl53pi0IK0Ys0ILkk8f900ynuviZ_Cc02g8NoMMRa97EylhS8CUfEQeS4kORvFPNp1K4cq7l_m27MKq5Y3zwQdUyNh5ntjDbu84n1CJQn4GihVdGXkU10VnNO8IUHNVhmlQLsxlv4KHmlacOwYiDJeL18BjG30Jmk9aaizTP3-W2bXrHv3nUOWF80_Xl3kEWNMgZW5FHYr-CQga4EDOcb-O_XHrM9c_bltaKA6evtdz5q33gBOvEuhFWrvb508QbY9U000R01b1D-urCQR9zwF3lTyxHjtgdAb3EIHP6vi6jIpy4Ph8Mfyde_KqRe7S1wJnYJ03Vxym8fXt7eWEukUrbQCjxtkYS0XfthkG25FUB4se_07ZiDyA-elyiBqx-MNqWzFQT_VPSE8vBhWFhrqCleGwNwFe7rIDxyayT_oqwbfNSwSSS93Q8m_Udq5mu9WBhLuJijttlfytS52OswKOyebQ; __Secure-access-token=9.99058575.a8li8rRbQOOY4BelAgeUZg.92.AQ3x6GVNRXUo4K0vxCPbAVTPlBmtYr2dh2oCQgqKGIFVvI5sVn7sM8jJrJBo8XKjYgOJBpeGgdf-ZPRyautCU3-GRY1_woiMnPNMlZojuhA4TnHQAX11y0Ks1jCO7tux4A.20220421183856.20251001114315.5x-ZROLzoHGSCwletsQroUuY8R-MAGuzSpUkkVQPubs.129f47120ae5e38b1; __Secure-refresh-token=9.99058575.a8li8rRbQOOY4BelAgeUZg.92.AQ3x6GVNRXUo4K0vxCPbAVTPlBmtYr2dh2oCQgqKGIFVvI5sVn7sM8jJrJBo8XKjYgOJBpeGgdf-ZPRyautCU3-GRY1_woiMnPNMlZojuhA4TnHQAX11y0Ks1jCO7tux4A.20220421183856.20251001114315.x_fiTIWfeuSdDdQ_GZXt70egzCeuDAJkZDFrx3cv93k.156fd9d6581f10c9f; __Secure-ETC=387a4168ff33b06c686219d3f926e9ba; __Secure-ab-group=92; __Secure-access-token=9.99058575.a8li8rRbQOOY4BelAgeUZg.92.AdSiy7jbvGpIK4izfTbXNOfQdXnd_DEZAsP3ktIM5FPd7ssIhlwqU3eNEoVme4hqCQKwY4dsJrWf3CPanqr6KbFWXO4yDJiW8vdmgYKMKZ1ZnybzAi5SabUX6sRfWSwqXA.20220421183856.20251001130833.hRmgRvzTKxGqPHbtUvLY71RYWhz7uJMivv7VC0GVzc8.14a710631302e2f60; __Secure-refresh-token=9.99058575.a8li8rRbQOOY4BelAgeUZg.92.AdSiy7jbvGpIK4izfTbXNOfQdXnd_DEZAsP3ktIM5FPd7ssIhlwqU3eNEoVme4hqCQKwY4dsJrWf3CPanqr6KbFWXO4yDJiW8vdmgYKMKZ1ZnybzAi5SabUX6sRfWSwqXA.20220421183856.20251001130833.bHcNI41CYqo90pqXaE_-p8wyuG3Sia5JjdGGsnUkpQ0.1dc5cfc8b20bc45a6; __Secure-user-id=99058575; abt_data=7.iCx6Q6qWKwR3mt2d8DsI0XMUckxoJuVjks0S05m_N4HC7mBUYMHYSzEqFLVTyACCtvBn-Lpra4IrddV96Bsp1XFjhwsszWyoLAPxJijfr0McoHYoFsmjoH7LcXpAlC08OCeDD77beOMwPiDLd5XKXs_VjiZhpUWQiLEGLW9CPblysPFqE586xg9_543mo_17Cn0YBbPk7-c-LsEzPvuXOexQPNvHN3sYikwKYW4jCnbrA9Xp-dmkUxYe1-rGThG7hjdz-cL8XdPQ63quzjbFdgZtLMEkW3TUjk3Txdf9zj8bOe3EQMsBaQUmU_V0T0Awwjpy4CxO6ku1bMd2GgvNyxKAXbLyPFrjmRX3dgwbKO0ypSVTdEXhVMoFqxv1qFGlloPW5F29bvgjMpKTUU4Bikq_w6i24XzzFEzvCjrpPxYRNivcC1UG5hE2grYcG4Igx5AN8C0_5XKEnh2IylzynP2mAP60_9d5P0Z1NOo35tMzbam6Njlb9ENp3zu0RuYUOZbQITOUPUfDPdNypMAPJx4A0BYxTa1ToOoXqy8i3iKJhMIi9H6KWhsm-Fs'
}
# Configure TLS settings similar to browser
tls_ciphers = [
    'TLS_AES_128_GCM_SHA256',
    'TLS_AES_256_GCM_SHA384',
    'TLS_CHACHA20_POLY1305_SHA256',
    'ECDHE-ECDSA-AES256-GCM-SHA384',
    'ECDHE-RSA-AES256-GCM-SHA384',
    'ECDHE-ECDSA-CHACHA20-POLY1305',
    'ECDHE-RSA-CHACHA20-POLY1305',
    'ECDHE-ECDSA-AES128-GCM-SHA256',
    'ECDHE-RSA-AES128-GCM-SHA256',
    'ECDHE-ECDSA-AES128-SHA256',
    'ECDHE-RSA-AES128-SHA256',
    'ECDHE-ECDSA-AES256-SHA',
    'ECDHE-RSA-AES256-SHA',
    'ECDHE-ECDSA-AES128-SHA',
    'ECDHE-RSA-AES128-SHA',
]

# Create custom SSL context
ssl_context = ssl.create_default_context()
ssl_context.options |= ssl.OP_NO_SSLv2
ssl_context.options |= ssl.OP_NO_SSLv3
ssl_context.options |= ssl.OP_NO_COMPRESSION
ssl_context.set_ciphers(':'.join(tls_ciphers))

# while True:
#     conn = http.client.HTTPSConnection(
#         "seller.ozon.ru",
#         context=ssl_context
#     )
#     conn.request("POST", "/api/pricing-bff-service/v3/get-common-prices", payload, headers)
#     res = conn.getresponse()
#     data = res.read()
#     logger.info(data.decode("utf-8"))
#     time.sleep(5)


from playwright.sync_api import sync_playwright

def make_request(page, url, headers, payload):
    request_data = {
        'url': f"https://seller.ozon.ru{url}",  # Added full URL
        'headers': headers,
        'body': payload
    }
    try:
        response = page.evaluate("""async (data) => {
            try {
                const response = await fetch(data.url, {
                    method: 'POST',
                    headers: data.headers,
                    body: JSON.stringify(data.body),
                    credentials: 'include'
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
            logger.error(f"Request failed: {response}")
            return None, response.get('error')
            
        logger.info(f"Request successful: {response}")
        return response, None
        
    except Exception as e:
        logger.error(f"Playwright error: {str(e)}")
        return None, str(e)

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
    response, error = make_request(page, "/api/pricing-bff-service/v3/get-common-prices", headers, payload)
    if error:
        print(f"Error occurred: {error}")
    else:
        print(f"Response: {response}")
    input()

if __name__ == '__main__':
    main()
