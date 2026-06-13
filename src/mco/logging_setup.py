"""
Logging configuration.

Default: human-readable loguru output (unchanged).
MCO_LOG_JSON=true: one JSON object per line on stderr - the shape log
shippers (Loki, Datadog, CloudWatch, ELK) ingest without a parser. Pairs
with /metrics so a deployment is observable on both axes.

MCO_LOG_LEVEL overrides the threshold (default INFO; DEBUG for noise).
"""

import os
import sys

from loguru import logger


def _truthy(v) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "on", "yes")


def configure_logging() -> None:
    """Apply the configured logging mode. Idempotent; safe to call at startup."""
    level = (os.environ.get("MCO_LOG_LEVEL") or "INFO").upper()
    json_mode = _truthy(os.environ.get("MCO_LOG_JSON"))

    logger.remove()
    if json_mode:
        # serialize=True emits loguru's structured record as JSON per line.
        logger.add(sys.stderr, level=level, serialize=True, backtrace=False, diagnose=False)
    else:
        logger.add(sys.stderr, level=level, backtrace=False, diagnose=False)
