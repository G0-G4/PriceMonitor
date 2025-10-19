import os
import json
import logging

logger = logging.getLogger(__name__)

try:
    with open("config.json") as f:
        config = json.load(f)
        LOG_LEVEL = config.get("LOG_LEVEL", "DEBUG")
        HEADLESS_BROWSER = config.get("HEADLESS_BROWSER", True)
        BROWSER_STARTUP_SLEEP_SECONDS = config.get("BROWSER_STARTUP_SLEEP_SECONDS", 5)
        SUSPEND_AFTER_BROWSER_STARTUP = config.get("SUSPEND_AFTER_BROWSER_STARTUP", False)
except Exception:
    logger.exception("failed to load config file")
