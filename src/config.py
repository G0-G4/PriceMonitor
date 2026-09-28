import os
import json
import logging

logger = logging.getLogger(__name__)

LOG_LEVEL = "DEBUG"
HEADLESS_BROWSER = True
BROWSER_STARTUP_SLEEP_SECONDS = 5
SUSPEND_AFTER_BROWSER_STARTUP = False
USER_DATA_DIR = "./browser_profile"
WB_WALLET_REFRESH_MINUTES = 60
WB_WALLET_LEVEL = "anonymous"

try:
    with open("config.json") as f:
        config = json.load(f)
        LOG_LEVEL = config.get("LOG_LEVEL", LOG_LEVEL)
        HEADLESS_BROWSER = config.get("HEADLESS_BROWSER", HEADLESS_BROWSER)
        BROWSER_STARTUP_SLEEP_SECONDS = config.get("BROWSER_STARTUP_SLEEP_SECONDS", BROWSER_STARTUP_SLEEP_SECONDS)
        SUSPEND_AFTER_BROWSER_STARTUP = config.get("SUSPEND_AFTER_BROWSER_STARTUP", SUSPEND_AFTER_BROWSER_STARTUP)
        USER_DATA_DIR = config.get("USER_DATA_DIR", USER_DATA_DIR)
        WB_WALLET_REFRESH_MINUTES = int(config.get("WB_WALLET_REFRESH_MINUTES", WB_WALLET_REFRESH_MINUTES))
        WB_WALLET_LEVEL = str(config.get("WB_WALLET_LEVEL", WB_WALLET_LEVEL)).strip() or WB_WALLET_LEVEL
except Exception:
    logger.exception("failed to load config file")

if WB_WALLET_REFRESH_MINUTES < 1:
    WB_WALLET_REFRESH_MINUTES = 1

