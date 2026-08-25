import pytest

from media_platform.international import RedditCrawler, YouTubeCrawler


@pytest.mark.asyncio
@pytest.mark.parametrize("crawler", [YouTubeCrawler(), RedditCrawler()])
async def test_rejects_non_search_mode(monkeypatch, crawler):
    monkeypatch.setattr("config.CRAWLER_TYPE", "detail")
    with pytest.raises(ValueError, match="keyword search only"):
        await crawler.start()
