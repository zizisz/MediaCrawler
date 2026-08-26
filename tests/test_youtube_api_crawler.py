from media_platform.youtube.core import YouTubeCrawler


def test_youtube_api_items_keep_keyword_and_relationships():
    video = {
        "id": "abc123",
        "snippet": {"title": "PEEK machining", "channelTitle": "Shop", "publishedAt": "2026-01-01T00:00:00Z"},
        "statistics": {"commentCount": "4"},
        "contentDetails": {"duration": "PT2M"},
    }
    content = YouTubeCrawler._content_item(video, "peek need")
    comment = YouTubeCrawler._comment_item(
        {"id": "c1", "snippet": {"textDisplay": "Need PEEK parts", "authorDisplayName": "Buyer"}},
        content,
        "peek need",
        None,
    )

    assert content["url"].endswith("abc123")
    assert comment["keyword"] == "peek need"
    assert comment["video_id"] == content["video_id"]
    assert comment["video_title"] == content["title"]
