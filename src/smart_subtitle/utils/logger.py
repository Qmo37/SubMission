"""Logging setup for smart_subtitle."""

import logging
import sys


def get_logger(name: str, level: str = "INFO") -> logging.Logger:
    """Get a configured logger."""
    logger = logging.getLogger(f"smart_subtitle.{name}")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        logger.addHandler(handler)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    return logger
