import os
import json
import logging

logger = logging.getLogger(__name__)

LOG_LEVEL = "DEBUG"
HEADLESS_BROWSER = True
BROWSER_STARTUP_SLEEP_SECONDS = 5
SUSPEND_AFTER_BROWSER_STARTUP = False
USER_DATA_DIR = "./browser_profile"
WB_USER_DATA_DIR = "./browser_profile_wb"

try:
    with open("config.json") as f:
        config = json.load(f)
        LOG_LEVEL = config.get("LOG_LEVEL", LOG_LEVEL)
        HEADLESS_BROWSER = config.get("HEADLESS_BROWSER", HEADLESS_BROWSER)
        BROWSER_STARTUP_SLEEP_SECONDS = config.get("BROWSER_STARTUP_SLEEP_SECONDS", BROWSER_STARTUP_SLEEP_SECONDS)
        SUSPEND_AFTER_BROWSER_STARTUP = config.get("SUSPEND_AFTER_BROWSER_STARTUP", SUSPEND_AFTER_BROWSER_STARTUP)
        USER_DATA_DIR = config.get("USER_DATA_DIR", USER_DATA_DIR)
        WB_USER_DATA_DIR = config.get("WB_USER_DATA_DIR", WB_USER_DATA_DIR)
except Exception:
    logger.exception("failed to load config file")
