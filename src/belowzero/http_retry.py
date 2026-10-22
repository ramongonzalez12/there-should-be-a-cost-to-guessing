"""Small standard-library helpers for provider-directed HTTP retry timing."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


def server_retry_delay(
    headers: Mapping[str, str] | None,
    *,
    now: datetime | None = None,
) -> float:
    """Return the server's requested delay without assuming one header format.

    RFC 9110 allows Retry-After to be seconds or an HTTP date. Some bulk-data
    providers instead publish the remaining reset time as ``t`` in a RateLimit
    header. An absent or malformed instruction returns zero so the caller can
    apply its own bounded exponential backoff.
    """
    if not headers:
        return 0.0

    retry_after = headers.get("Retry-After")
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(retry_after)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                observed_at = now or datetime.now(timezone.utc)
                return max(0.0, (retry_at - observed_at).total_seconds())
            except (TypeError, ValueError, OverflowError):
                pass

    rate_limit = headers.get("RateLimit")
    if rate_limit:
        match = re.search(r"(?:^|[;,])\s*t=(\d+(?:\.\d+)?)\b", rate_limit)
        if match:
            return max(0.0, float(match.group(1)))
    return 0.0
