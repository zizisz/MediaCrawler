from datetime import UTC, datetime
from types import SimpleNamespace

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
