"""Shared date and sorting options for YouTube and X searches."""
import os
from datetime import datetime, timedelta, timezone


def search_options(now=None):
    now = now or datetime.now(timezone.utc)
    period = os.getenv("INTERNATIONAL_SEARCH_RANGE", "year")
    sort = os.getenv("INTERNATIONAL_SEARCH_SORT", "latest")
    if period not in {"month", "year", "this_year", "all"} or sort not in {"latest", "relevance"}:
        raise ValueError("Invalid international search range or sort")
    after = None
    if period in {"month", "year"}:
        after = now - timedelta(days=30 if period == "month" else 365)
    elif period == "this_year":
        after = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return after, sort
