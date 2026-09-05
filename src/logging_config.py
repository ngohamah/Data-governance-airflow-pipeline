"""Shared logging setup: every module gets the same file + console handlers.

Call get_logger(__name__) from any module instead of configuring logging locally,
so all pipeline output lands in one place (logs/pipeline.log) for traceability.
"""

from __future__ import annotations

import logging

from src.config import LOG_FILE_PATH, LOGS_DIR

_CONFIGURED = False


def _configure_root() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(LOG_FILE_PATH, encoding="utf-8")
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a module-level logger, ensuring shared handlers are configured once."""
    _configure_root()
    return logging.getLogger(name)
