"""Shared severity filtering; diagnostics go only to container stderr."""
import logging
import sys

from .settings import ConfigError, LOG_LEVELS

logger = logging.getLogger("watermeter")
logger.propagate = False


def configure(level="info"):
    if level not in LOG_LEVELS:
        raise ConfigError("LOG_LEVEL must be debug, info, warning, error or critical")
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    for previous in logger.handlers[:]:
        logger.removeHandler(previous)
        previous.close()
    logger.addHandler(handler)
    logger.setLevel(level.upper())


def log(message, level=logging.INFO):
    if not logger.handlers:
        configure()
    logger.log(level, message)
