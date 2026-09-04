from datetime import datetime, timezone
import pytest
from tools.international_search import search_options
from api.schemas.crawler import CrawlerStartRequest
import asyncio
import config
from media_platform.youtube.core import YouTubeCrawler
from media_platform.x.core import XCrawler


def test_search_ranges_and_validation(monkeypatch):
    now = datetime(2026, 9, 4, tzinfo=timezone.utc)
    for period, expected in [("month", "2026-08-05"), ("year", "2025-09-04"), ("this_year", "2026-01-01"), ("all", None)]:
        monkeypatch.setenv("INTERNATIONAL_SEARCH_RANGE", period)
        monkeypatch.setenv("INTERNATIONAL_SEARCH_SORT", "latest")
        after, sort = search_options(now)
        assert (after.date().isoformat() if after else None) == expected
        assert sort == "latest"
    monkeypatch.setenv("INTERNATIONAL_SEARCH_SORT", "relevance")
    assert search_options(now)[1] == "relevance"
    config = CrawlerStartRequest(platform="youtube")
    assert (config.search_time_range, config.search_sort) == ("year", "latest")
    with pytest.raises(ValueError):
        CrawlerStartRequest(platform="x", search_time_range="invalid")


def test_platform_requests_receive_filters(monkeypatch):
    monkeypatch.setattr(config, "KEYWORDS", "PEEK")
    monkeypatch.setattr(config, "CRAWLER_MAX_NOTES_COUNT", 20)
    youtube = YouTubeCrawler()
    captured = []

    async def fake_get(endpoint, **params):
        captured.append(params)
        return {"items": []}

    class FakeAPI:
        async def search(self, query, **kwargs):
            captured.append({"query": query, **kwargs})
            for item in []:
                yield item

    monkeypatch.setattr(youtube, "_get", fake_get)
    x = XCrawler()
    x.api = FakeAPI()
    for period, sort in [("this_year", "latest"), ("all", "relevance")]:
        monkeypatch.setenv("INTERNATIONAL_SEARCH_RANGE", period)
        monkeypatch.setenv("INTERNATIONAL_SEARCH_SORT", sort)
        asyncio.run(youtube._search_videos("PEEK"))
        assert captured[-1]["order"] == ("date" if sort == "latest" else "relevance")
        assert ("publishedAfter" in captured[-1]) == (period != "all")
        asyncio.run(x.search())
        assert ("since:" in captured[-1]["query"]) == (period != "all")
        assert captured[-1]["kv"]["product"] == ("Latest" if sort == "latest" else "Top")
