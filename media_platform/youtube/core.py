import os
from typing import Any

import httpx

import config
from base.base_crawler import AbstractCrawler
from tools.async_file_writer import AsyncFileWriter
from tools.youtube_quota import record_youtube_quota
from var import crawler_type_var, source_keyword_var


API_BASE = "https://www.googleapis.com/youtube/v3"
PROXY = os.getenv("INTERNATIONAL_PROXY", "http://127.0.0.1:7890")


class YouTubeAPIError(RuntimeError):
    def __init__(self, reason: str, message: str):
        self.reason = reason
        super().__init__(f"YouTube API error [{reason}]: {message}")


class YouTubeCrawler(AbstractCrawler):
    platform = "youtube"

    def __init__(self):
        self.api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
        self.client: httpx.AsyncClient | None = None

    async def start(self):
        if not self.api_key:
            raise ValueError("YOUTUBE_API_KEY is not configured on the server")
        if config.CRAWLER_TYPE != "search":
            raise ValueError("YouTube currently supports keyword search only")
        if config.SAVE_DATA_OPTION not in {"json", "jsonl", "csv"}:
            raise ValueError("YouTube currently supports JSON, JSONL and CSV storage only")
        if config.CRAWLER_MAX_NOTES_COUNT > 500:
            raise ValueError("YouTube supports at most 500 videos per keyword")

        crawler_type_var.set(config.CRAWLER_TYPE)
        self.client = httpx.AsyncClient(
            proxy=PROXY,
            timeout=httpx.Timeout(30.0),
            trust_env=False,
            headers={"X-Goog-Api-Key": self.api_key},
        )
        try:
            await self.search()
        finally:
            await self.client.aclose()
            self.client = None

    async def search(self):
        writer = AsyncFileWriter(platform=self.platform, crawler_type="search")
        for keyword in filter(None, map(str.strip, config.KEYWORDS.split(","))):
            source_keyword_var.set(keyword)
            videos = await self._search_videos(keyword)
            comment_count = 0
            for index, video in enumerate(videos, 1):
                content = self._content_item(video, keyword)
                await self._write(writer, content, "contents")
                comments: list[dict[str, Any]] = []
                if config.ENABLE_GET_COMMENTS:
                    comments = await self._video_comments(content, keyword)
                    for comment in comments:
                        await self._write(writer, comment, "comments")
                    comment_count += len(comments)
                print(
                    f"[youtube] {keyword}: saved {index}/{len(videos)} videos; "
                    f"this video {len(comments)} comments; total {comment_count} comments"
                )

    async def _get(self, endpoint: str, **params) -> dict[str, Any]:
        assert self.client is not None
        response = await self.client.get(f"{API_BASE}/{endpoint}", params=params)
        record_youtube_quota(endpoint)
        if response.is_success:
            return response.json()

        reason = f"http_{response.status_code}"
        message = response.reason_phrase
        try:
            error = response.json().get("error", {})
            message = error.get("message", message)
            details = error.get("errors") or []
            if details:
                reason = details[0].get("reason", reason)
        except ValueError:
            pass
        raise YouTubeAPIError(reason, message)

    async def _search_videos(self, keyword: str) -> list[dict[str, Any]]:
        videos: list[dict[str, Any]] = []
        page_token = None
        limit = config.CRAWLER_MAX_NOTES_COUNT

        while len(videos) < limit:
            page_size = min(50, limit - len(videos))
            params = {
                "part": "snippet",
                "q": keyword,
                "type": "video",
                "maxResults": page_size,
                "order": "relevance",
            }
            if page_token:
                params["pageToken"] = page_token

            search_data = await self._get("search", **params)
            video_ids = [item["id"]["videoId"] for item in search_data.get("items", [])]
            if not video_ids:
                break

            detail_data = await self._get(
                "videos",
                part="snippet,statistics,contentDetails",
                id=",".join(video_ids),
            )
            by_id = {item["id"]: item for item in detail_data.get("items", [])}
            videos.extend(by_id[video_id] for video_id in video_ids if video_id in by_id)

            page_token = search_data.get("nextPageToken")
            if not page_token:
                break

        return videos[:limit]

    async def _video_comments(self, content: dict[str, Any], keyword: str) -> list[dict[str, Any]]:
        comments: list[dict[str, Any]] = []
        page_token = None
        limit = config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES

        try:
            while len(comments) < limit:
                params = {
                    "part": "snippet",
                    "videoId": content["video_id"],
                    "maxResults": min(100, limit - len(comments)),
                    "order": "relevance",
                    "textFormat": "plainText",
                }
                if page_token:
                    params["pageToken"] = page_token
                data = await self._get("commentThreads", **params)

                for thread in data.get("items", []):
                    top = thread["snippet"]["topLevelComment"]
                    comments.append(self._comment_item(top, content, keyword, None))
                    if len(comments) >= limit:
                        break
                    if config.ENABLE_GET_SUB_COMMENTS and thread["snippet"].get("totalReplyCount", 0):
                        replies = await self._replies(top["id"], limit - len(comments))
                        comments.extend(
                            self._comment_item(reply, content, keyword, top["id"])
                            for reply in replies
                        )
                    if len(comments) >= limit:
                        break

                page_token = data.get("nextPageToken")
                if not page_token or not data.get("items"):
                    break
        except YouTubeAPIError as exc:
            if exc.reason in {"commentsDisabled", "videoNotFound"}:
                print(f"[youtube] comments unavailable for {content['video_id']}: {exc.reason}")
                return comments
            raise
        return comments[:limit]

    async def _replies(self, parent_id: str, limit: int) -> list[dict[str, Any]]:
        replies: list[dict[str, Any]] = []
        page_token = None
        while len(replies) < limit:
            params = {
                "part": "snippet",
                "parentId": parent_id,
                "maxResults": min(100, limit - len(replies)),
                "textFormat": "plainText",
            }
            if page_token:
                params["pageToken"] = page_token
            data = await self._get("comments", **params)
            replies.extend(data.get("items", []))
            page_token = data.get("nextPageToken")
            if not page_token or not data.get("items"):
                break
        return replies[:limit]

    @staticmethod
    def _content_item(video: dict[str, Any], keyword: str) -> dict[str, Any]:
        snippet = video.get("snippet", {})
        statistics = video.get("statistics", {})
        return {
            "platform": "youtube",
            "keyword": keyword,
            "video_id": video.get("id"),
            "title": snippet.get("title"),
            "description": snippet.get("description"),
            "author": snippet.get("channelTitle"),
            "channel_id": snippet.get("channelId"),
            "publish_time": snippet.get("publishedAt"),
            "duration": video.get("contentDetails", {}).get("duration"),
            "view_count": statistics.get("viewCount"),
            "like_count": statistics.get("likeCount"),
            "comment_count": statistics.get("commentCount"),
            "url": f"https://www.youtube.com/watch?v={video.get('id')}",
        }

    @staticmethod
    def _comment_item(
        comment: dict[str, Any],
        content: dict[str, Any],
        keyword: str,
        parent_id: str | None,
    ) -> dict[str, Any]:
        snippet = comment.get("snippet", {})
        return {
            "platform": "youtube",
            "keyword": keyword,
            "video_id": content["video_id"],
            "video_title": content.get("title"),
            "comment_id": comment.get("id"),
            "parent_comment_id": parent_id,
            "content": snippet.get("textDisplay"),
            "author": snippet.get("authorDisplayName"),
            "like_count": snippet.get("likeCount"),
            "publish_time": snippet.get("publishedAt"),
            "url": content["url"],
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
