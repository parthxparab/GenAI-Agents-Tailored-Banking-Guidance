import json
import logging
import os
from typing import Any, Dict

import redis

logger = logging.getLogger(__name__)

redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
r = redis.from_url(redis_url)


def publish(channel: str, message: Dict[str, Any]) -> None:
    """Publish a JSON message to the specified Redis channel."""
    payload = json.dumps(message, default=str)
    r.publish(channel, payload)
    logger.info("Published message to %s: %s", channel, payload)


__all__ = ["r", "publish"]
