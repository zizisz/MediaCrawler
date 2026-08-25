import pytest

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
