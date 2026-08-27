import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import config
from media_platform.x import core as x_core
from media_platform.x.core import XCrawler


def test_x_items_keep_search_and_reply_relationships():
    user = SimpleNamespace(id_str="7", username="buyer", displayname="Buyer")
    tweet = SimpleNamespace(
        id_str="10", rawContent="need PEEK parts", user=user,
        date=datetime(2026, 8, 27, tzinfo=UTC), replyCount=2,
        retweetCount=3, likeCount=4, viewCount=5, url="https://x.com/buyer/status/10",
    )
    content = XCrawler._content_item(tweet, "PEEK")
    reply = SimpleNamespace(
        id_str="11", inReplyToTweetIdStr="10", rawContent="We can help", user=user,
        date=datetime(2026, 8, 27, tzinfo=UTC), likeCount=1,
        url="https://x.com/buyer/status/11",
    )

    assert content["tweet_id"] == "10" and content["keyword"] == "PEEK"
    assert XCrawler._comment_item(reply, content, "PEEK")["parent_comment_id"] == "10"


def test_x_search_never_saves_more_than_requested(monkeypatch):
    user = SimpleNamespace(id_str="7", username="buyer", displayname="Buyer")

    class FakeAPI:
        async def search(self, *_args, **_kwargs):
            for index in range(3):
                yield SimpleNamespace(
                    id_str=str(index), rawContent="PEEK", user=user,
                    date=datetime(2026, 8, 27, tzinfo=UTC), replyCount=0,
                    retweetCount=0, likeCount=0, viewCount=0, url=f"https://x.com/i/{index}",
                )

    crawler = XCrawler()
    crawler.api = FakeAPI()
    written = []

    async def capture(_writer, item, _item_type):
        written.append(item)

    monkeypatch.setattr(crawler, "_write", capture)
    monkeypatch.setattr(config, "KEYWORDS", "PEEK")
    monkeypatch.setattr(config, "CRAWLER_MAX_NOTES_COUNT", 2)
    monkeypatch.setattr(config, "CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES", 10)
    monkeypatch.setattr(config, "ENABLE_GET_COMMENTS", False)

    asyncio.run(crawler.search())
    assert len(written) == 2


def test_x_reuses_saved_account_when_cookie_field_is_empty(tmp_path, monkeypatch):
    account = SimpleNamespace(active=True, cookies={"auth_token": "saved", "ct0": "saved"})

    class FakePool:
        async def get(self, username):
            assert username == "webui"
            return account

    class FakeAPI:
        def __init__(self, *_args, **_kwargs):
            self.pool = FakePool()

    crawler = XCrawler()

    async def no_search():
        pass

    monkeypatch.delenv("X_COOKIES", raising=False)
    monkeypatch.setattr(x_core, "ACCOUNT_DB", tmp_path / "accounts.db")
    monkeypatch.setattr(x_core, "API", FakeAPI)
    monkeypatch.setattr(config, "CRAWLER_TYPE", "search")
    monkeypatch.setattr(config, "SAVE_DATA_OPTION", "json")
    monkeypatch.setattr(config, "CRAWLER_MAX_NOTES_COUNT", 20)
    monkeypatch.setattr(crawler, "search", no_search)

    asyncio.run(crawler.start())
