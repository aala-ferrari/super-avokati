"""Shared logger configuration."""
from __future__ import annotations

import logging
import sys

from .config import LOG_PATH

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(_FORMAT)

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    logger.addHandler(stream)

    # v9.344 — rotazione (10 MB × 5): il log ora vive sul VOLUME (run.sh monta logs/) e sopravvive
    # ai deploy, quindi non può crescere per sempre
    from logging.handlers import RotatingFileHandler
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    except Exception:  # noqa: BLE001
        pass
    file_handler = RotatingFileHandler(LOG_PATH, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    logger.propagate = False
    return logger
