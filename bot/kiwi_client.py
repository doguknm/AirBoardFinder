"""Kiwi Tequila client — deprecated, now B2B-only.

This stub exists so existing test imports resolve cleanly.
The scheduler no longer calls this module.
"""

from __future__ import annotations

import logging
from typing import Any


LOGGER = logging.getLogger(__name__)
KIWI_SEARCH_URL = "https://api.tequila.kiwi.com/v2/search"


async def fetch_price(
    origin: str,
    destination: str,
    date_from: str,
    date_to: str,
    api_key: str,
) -> dict[str, Any] | None:
    LOGGER.warning(
        "kiwi_client.fetch_price called but Kiwi Tequila is B2B-only. "
        "Use travelpayouts_client instead."
    )
    return None
