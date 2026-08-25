import pytest
from types import SimpleNamespace

from media_platform.international import RedditCrawler, YouTubeCrawler


@pytest.mark.asyncio
@pytest.mark.parametrize("crawler", [YouTubeCrawler(), RedditCrawler()])
async def test_rejects_non_search_mode(monkeypatch, crawler):
    monkeypatch.setattr("config.CRAWLER_TYPE", "detail")
    with pytest.raises(ValueError, match="keyword search only"):
        await crawler.start()


def test_youtube_comment_normalization():
    comments = []
    YouTubeCrawler._append_comments(comments, [{"id": "1", "text": "ok", "like_count": 2}], "peek", "v", "u")
    assert comments == [{
        "platform": "youtube", "keyword": "peek", "video_id": "v", "comment_id": "1",
        "parent_comment_id": None, "content": "ok", "author": None, "like_count": 2,
        "publish_time": None, "url": "u",
    }]


def test_youtube_detects_google_rate_limit():
    response = SimpleNamespace(status_code=429, url="https://www.google.com/sorry/index")
    assert YouTubeCrawler._is_rate_limited(response)


@pytest.mark.asyncio
async def test_youtube_saves_each_video_immediately(monkeypatch):
    crawler, saved = YouTubeCrawler(), []
    monkeypatch.setattr("config.KEYWORDS", "peek")
    monkeypatch.setattr("config.ENABLE_GET_COMMENTS", False)
    monkeypatch.setattr(crawler, "_search_videos", lambda _: [{"id": "1"}, {"id": "2"}])

    async def save(_, item, item_type):
        saved.append((item["video_id"], item_type))

    monkeypatch.setattr(crawler, "_write", save)
    await crawler.search()
    assert saved == [("1", "contents"), ("2", "contents")]
