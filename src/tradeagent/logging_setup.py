"""Logging to a rotating file (and optionally the console), timestamps in UTC."""

from __future__ import annotations

import logging
import time
from logging.handlers import RotatingFileHandler

from tradeagent.config import Settings

_FORMAT = "%(asctime)s.%(msecs)03dZ %(levelname)-7s %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%dT%H:%M:%S"


class _UTCFormatter(logging.Formatter):
    converter = time.gmtime


def setup_logging(settings: Settings, *, console: bool = True) -> logging.Logger:
    """Configure the "tradeagent" logger tree and return it."""
    logger = logging.getLogger("tradeagent")
    logger.setLevel(settings.logging.level)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    formatter = _UTCFormatter(_FORMAT, _DATEFMT)

    log_path = settings.resolve(settings.logging.file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_path, maxBytes=settings.logging.max_bytes, backupCount=settings.logging.backups, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    logger.propagate = False
    return logger
