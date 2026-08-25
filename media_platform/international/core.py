import asyncio
import os
import random
from typing import Any, Dict

import config
from base.base_crawler import AbstractCrawler
from tools.async_file_writer import AsyncFileWriter
from var import crawler_type_var, source_keyword_var


PROXY = os.getenv("INTERNATIONAL_PROXY", "http://127.0.0.1:7890")


class _QuietYtDlpLogger:
    debug = warning = error = lambda *args, **kwargs: None


class InternationalCrawler(AbstractCrawler):
    platform = ""

    async def start(self):
        if config.CRAWLER_TYPE != "search":
            raise ValueError(f"{self.platform} currently supports keyword search only")
        if config.SAVE_DATA_OPTION not in {"json", "jsonl", "csv"}:
            raise ValueError(f"{self.platform} currently supports JSON, JSONL and CSV storage only")
        if self.platform == "youtube" and config.CRAWLER_MAX_NOTES_COUNT > 500:
            raise ValueError("YouTube supports at most 500 videos per keyword")
        crawler_type_var.set(config.CRAWLER_TYPE)
        await self.search()

    async def search(self):
        writer = AsyncFileWriter(platform=self.platform, crawler_type="search")
        for keyword in filter(None, map(str.strip, config.KEYWORDS.split(","))):
            source_keyword_var.set(keyword)
            contents, comments = await asyncio.to_thread(self._crawl_keyword, keyword)
            for item in contents:
                await self._write(writer, item, "contents")
            if config.ENABLE_GET_COMMENTS:
                for item in comments:
                    await self._write(writer, item, "comments")
            print(f"[{self.platform}] {keyword}: {len(contents)} contents, {len(comments)} comments")

    async def _write(self, writer: AsyncFileWriter, item: Dict[str, Any], item_type: str):
        if config.SAVE_DATA_OPTION == "csv":
            await writer.write_to_csv(item, item_type)
        elif config.SAVE_DATA_OPTION == "jsonl":
            await writer.write_to_jsonl(item, item_type)
        else:
            await writer.write_single_item_to_json(item, item_type)

    def _crawl_keyword(self, keyword: str) -> tuple[list[Dict], list[Dict]]:
        raise NotImplementedError

    async def launch_browser(self, *args, **kwargs):
        raise NotImplementedError


class YouTubeCrawler(InternationalCrawler):
    platform = "youtube"

    async def search(self):
        writer = AsyncFileWriter(platform=self.platform, crawler_type="search")
        for keyword in filter(None, map(str.strip, config.KEYWORDS.split(","))):
            source_keyword_var.set(keyword)
            videos = await asyncio.to_thread(self._search_videos, keyword)
            comment_count = 0
            for index, video in enumerate(videos, 1):
                content = self._content_item(video, keyword)
                await self._write(writer, content, "contents")
                if config.ENABLE_GET_COMMENTS:
                    comments = await asyncio.to_thread(self._video_comments, content, keyword)
                    for comment in comments:
                        await self._write(writer, comment, "comments")
                    comment_count += len(comments)
                print(
                    f"[youtube] {keyword}: saved {index}/{len(videos)} videos; "
                    f"this video {len(comments) if config.ENABLE_GET_COMMENTS else 0} comments; "
                    f"total {comment_count} comments"
                )
                if index < len(videos):
                    delay = random.uniform(5, 10) if config.CRAWLER_MAX_NOTES_COUNT == 500 else random.uniform(2, 5)
                    print(f"[youtube] waiting {delay:.1f}s before the next video")
                    await asyncio.sleep(delay)

    @staticmethod
    def _search_videos(keyword):
        import yt_dlp

        options = {"quiet": True, "extract_flat": True, "proxy": PROXY}
        with yt_dlp.YoutubeDL(options) as ydl:
            result = ydl.extract_info(f"ytsearch{config.CRAWLER_MAX_NOTES_COUNT}:{keyword}", download=False)
        return (result or {}).get("entries") or []

    def _content_item(self, video, keyword):
        video_id = video.get("id")
        return {
            "platform": self.platform, "keyword": keyword, "video_id": video_id,
            "title": video.get("title"), "author": video.get("channel") or video.get("uploader"),
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "duration": video.get("duration"), "view_count": video.get("view_count"),
        }

    def _video_comments(self, content, keyword):
        import yt_dlp
        from youtube_comment_downloader import YoutubeCommentDownloader

        video_id, url = content["video_id"], content["url"]
        comments = []
        downloader = YoutubeCommentDownloader()
        downloader.session.proxies.update({"http": PROXY, "https": PROXY})
        try:
            self._append_comments(comments, downloader.get_comments_from_url(url), keyword, video_id, url)
        except Exception:
            response = downloader.session.get(url)
            if self._is_rate_limited(response):
                print(f"[youtube] comments rate-limited for {video_id} (HTTP 429); change the mihomo node")
                return comments
            print(f"[youtube] primary comment parser unsupported for {video_id}; trying yt-dlp")
            try:
                options = {
                    "quiet": True, "skip_download": True, "getcomments": True, "proxy": PROXY,
                    "logger": _QuietYtDlpLogger(),
                    "extractor_args": {"youtube": {"max_comments": [str(config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES)]}},
                }
                with yt_dlp.YoutubeDL(options) as ydl:
                    detail = ydl.extract_info(url, download=False)
                self._append_comments(comments, (detail or {}).get("comments") or [], keyword, video_id, url)
            except Exception:
                print(f"[youtube] comments skipped for {video_id}")
        return comments

    @staticmethod
    def _is_rate_limited(response):
        return response.status_code == 429 or "google.com/sorry" in response.url

    def _crawl_keyword(self, keyword: str) -> tuple[list[Dict], list[Dict]]:
        contents, comments = [], []
        for video in self._search_videos(keyword):
            content = self._content_item(video, keyword)
            contents.append(content)
            if config.ENABLE_GET_COMMENTS:
                comments.extend(self._video_comments(content, keyword))
        return contents, comments

    @staticmethod
    def _append_comments(target, source, keyword, video_id, url):
        for index, comment in enumerate(source):
            if index >= config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES:
                break
            target.append({
                "platform": "youtube", "keyword": keyword, "video_id": video_id,
                "comment_id": comment.get("cid") or comment.get("id"),
                "parent_comment_id": comment.get("parent"),
                "content": comment.get("text"), "author": comment.get("author"),
                "like_count": comment.get("votes") or comment.get("like_count"),
                "publish_time": comment.get("time") or comment.get("timestamp"), "url": url,
            })


class RedditCrawler(InternationalCrawler):
    platform = "reddit"

    def _crawl_keyword(self, keyword: str) -> tuple[list[Dict], list[Dict]]:
        import praw
        import requests

        client_id = os.getenv("REDDIT_CLIENT_ID")
        client_secret = os.getenv("REDDIT_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise ValueError("Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET for Reddit")

        session = requests.Session()
        session.proxies.update({"http": PROXY, "https": PROXY})
        reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=os.getenv("REDDIT_USER_AGENT", "MediaCrawler/0.1 by jutai"),
            requestor_kwargs={"session": session},
        )
        contents, comments = [], []
        for submission in reddit.subreddit("all").search(keyword, limit=config.CRAWLER_MAX_NOTES_COUNT):
            url = f"https://www.reddit.com{submission.permalink}"
            contents.append({
                "platform": self.platform, "keyword": keyword, "post_id": submission.id,
                "title": submission.title, "content": submission.selftext, "author": str(submission.author),
                "subreddit": str(submission.subreddit), "url": url, "score": submission.score,
                "comment_count": submission.num_comments, "publish_time": int(submission.created_utc),
            })
            if not config.ENABLE_GET_COMMENTS:
                continue
            submission.comments.replace_more(limit=0)
            for comment in submission.comments.list()[:config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES]:
                comments.append({
                    "platform": self.platform, "keyword": keyword, "post_id": submission.id,
                    "comment_id": comment.id, "parent_comment_id": comment.parent_id,
                    "content": comment.body, "author": str(comment.author), "score": comment.score,
                    "publish_time": int(comment.created_utc), "url": url,
                })
        return contents, comments
