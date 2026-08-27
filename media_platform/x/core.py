import os
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any

import config
from base.base_crawler import AbstractCrawler
from tools.async_file_writer import AsyncFileWriter
from twscrape import API
from var import crawler_type_var, source_keyword_var


PROXY = os.getenv("INTERNATIONAL_PROXY", "http://127.0.0.1:7890")
ACCOUNT_DB = Path(__file__).parents[2] / "data" / "x" / "accounts.db"


class XCrawler(AbstractCrawler):
    platform = "x"

    async def start(self):
        cookies = os.getenv("X_COOKIES", "").strip()
        if config.CRAWLER_TYPE != "search":
            raise ValueError("X currently supports keyword search only")
        if config.SAVE_DATA_OPTION not in {"json", "jsonl", "csv"}:
            raise ValueError("X currently supports JSON, JSONL and CSV storage only")
        if config.CRAWLER_MAX_NOTES_COUNT > 500:
            raise ValueError("X supports at most 500 posts per keyword")

        crawler_type_var.set(config.CRAWLER_TYPE)
        ACCOUNT_DB.parent.mkdir(parents=True, exist_ok=True)
        self.api = API(str(ACCOUNT_DB), proxy=PROXY, raise_when_no_account=True)
        if cookies:
            parsed = SimpleCookie()
            parsed.load(cookies)
            if not {"auth_token", "ct0"}.issubset(parsed):
                raise ValueError("X Cookie must contain auth_token and ct0")
            await self.api.pool.delete_accounts("webui")
            await self.api.pool.add_account("webui", "", "", "", cookies=cookies, proxy=PROXY)
        else:
            account = await self.api.pool.get("webui")
            if not account or not account.active or not {"auth_token", "ct0"}.issubset(account.cookies):
                raise ValueError("Paste an X Cookie once to save the default account")
        await self.search()

    async def search(self):
        writer = AsyncFileWriter(platform=self.platform, crawler_type="search")
        limit = config.CRAWLER_MAX_NOTES_COUNT
        reply_limit = config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES
        for keyword in filter(None, map(str.strip, config.KEYWORDS.split(","))):
            source_keyword_var.set(keyword)
            saved = comments_saved = 0
            async for tweet in self.api.search(keyword, limit=limit):
                if saved >= limit:
                    break
                content = self._content_item(tweet, keyword)
                await self._write(writer, content, "contents")
                saved += 1
                replies = []
                if config.ENABLE_GET_COMMENTS and tweet.replyCount:
                    async for reply in self.api.tweet_replies(tweet.id, limit=reply_limit + 1):
                        if reply.id == tweet.id:
                            continue
                        if not config.ENABLE_GET_SUB_COMMENTS and reply.inReplyToTweetId != tweet.id:
                            continue
                        replies.append(reply)
                        if len(replies) >= reply_limit:
                            break
                    for reply in replies:
                        await self._write(writer, self._comment_item(reply, content, keyword), "comments")
                    comments_saved += len(replies)
                print(
                    f"[x] {keyword}: saved {saved}/{limit} posts; "
                    f"this post {len(replies)} replies; total {comments_saved} replies"
                )

    @staticmethod
    def _content_item(tweet: Any, keyword: str) -> dict[str, Any]:
        return {
            "platform": "x",
            "keyword": keyword,
            "tweet_id": tweet.id_str,
            "content": tweet.rawContent,
            "author": tweet.user.displayname,
            "author_id": tweet.user.id_str,
            "author_username": tweet.user.username,
            "publish_time": tweet.date.isoformat(),
            "reply_count": tweet.replyCount,
            "retweet_count": tweet.retweetCount,
            "like_count": tweet.likeCount,
            "view_count": tweet.viewCount,
            "url": tweet.url,
        }

    @staticmethod
    def _comment_item(tweet: Any, content: dict[str, Any], keyword: str) -> dict[str, Any]:
        return {
            "platform": "x",
            "keyword": keyword,
            "tweet_id": content["tweet_id"],
            "comment_id": tweet.id_str,
            "parent_comment_id": tweet.inReplyToTweetIdStr,
            "content": tweet.rawContent,
            "author": tweet.user.displayname,
            "author_id": tweet.user.id_str,
            "author_username": tweet.user.username,
            "like_count": tweet.likeCount,
            "publish_time": tweet.date.isoformat(),
            "url": tweet.url,
        }

    async def _write(self, writer: AsyncFileWriter, item: dict[str, Any], item_type: str):
        if config.SAVE_DATA_OPTION == "csv":
            await writer.write_to_csv(item, item_type)
        elif config.SAVE_DATA_OPTION == "jsonl":
            await writer.write_to_jsonl(item, item_type)
        else:
            await writer.write_single_item_to_json(item, item_type)

    async def launch_browser(self, *args, **kwargs):
        raise NotImplementedError
