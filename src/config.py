import os
import json
import logging

logger = logging.getLogger(__name__)

try:
    with open("config.json") as f:
        config = json.load(f)
        LOG_LEVEL = config.get("LOG_LEVEL", "DEBUG")
        HEADLESS_BROWSER = config.get("HEADLESS_BROWSER", True)
except Exception:
    logger.exception("failed to load config file")
