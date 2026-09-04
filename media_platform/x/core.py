import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any

import config
from base.base_crawler import AbstractCrawler
from tools.async_file_writer import AsyncFileWriter
from tools.international_search import search_options
from twscrape import API
from twscrape.accounts_pool import NoAccountError
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
                raise SystemExit("[x] ERROR：Cookie 不完整，需要包含 auth_token 和 ct0；请重新粘贴完整 Cookie。")
            await self.api.pool.delete_accounts("webui")
            await self.api.pool.add_account("webui", "", "", "", cookies=cookies, proxy=PROXY)
        else:
            account = await self.api.pool.get("webui")
            if not account or not account.active or not {"auth_token", "ct0"}.issubset(account.cookies):
                raise SystemExit("[x] ERROR：没有可用的已登录账号（未配置、已停用或登录信息不完整）。请在浏览器确认 X 账号能正常使用，再更新 Cookie。")
        try:
            await self.search()
        except NoAccountError as error:
            queue = str(error).rsplit(" ", 1)[-1]
            accounts = await self.api.pool.get_all()
            raise SystemExit(self._unavailable_message(accounts, queue)) from None

    @staticmethod
    def _unavailable_message(accounts, queue, now=None):
        now = now or datetime.now(timezone.utc)
        active = [account for account in accounts if account.active]
        if not active:
            return "[x] ERROR：没有可用账号，登录可能失效或账号被停用。请在浏览器确认 X 账号状态，再更新 Cookie。已保存的数据保留。"
        locks = [account.locks[queue] for account in active if queue in account.locks and account.locks[queue] > now]
        if locks:
            available = min(locks).astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")
            return f"[x] ERROR：{queue} 暂不可用（可能限流或临时占用），预计北京时间 {available} 后可重试，以 X 实际状态为准。无需立即更换 Cookie；本次已停止，已保存的数据保留。"
        return f"[x] ERROR：{queue} 暂无可用账号，恢复时间未知。请稍后重试；若持续发生，请检查 X 账号登录状态。已保存的数据保留。"

    async def search(self):
        writer = AsyncFileWriter(platform=self.platform, crawler_type="search")
        limit = config.CRAWLER_MAX_NOTES_COUNT
        reply_limit = config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES
        after, sort = search_options()
        print(f"[x] search: since {after.date() if after else 'all time'}, sort={sort}")
        for keyword in filter(None, map(str.strip, config.KEYWORDS.split(","))):
            source_keyword_var.set(keyword)
            saved = comments_saved = 0
            query = f"({keyword}) since:{after.date()}" if after else keyword
            async for tweet in self.api.search(query, limit=limit, kv={"product": "Latest" if sort == "latest" else "Top"}):
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
