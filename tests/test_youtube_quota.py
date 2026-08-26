from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tools.youtube_quota import QUOTA_FILE, record_youtube_quota, youtube_quota_snapshot


def test_quota_state_is_outside_managed_crawl_data():
    project_data = Path(__file__).parent.parent / "data"
    assert not QUOTA_FILE.is_relative_to(project_data)


def test_youtube_quota_tracks_buckets_and_resets_at_pacific_midnight(tmp_path):
    path = tmp_path / "quota.json"
    pacific = ZoneInfo("America/Los_Angeles")
    before_midnight = datetime(2026, 8, 25, 23, 59, tzinfo=pacific)

    record_youtube_quota("search", path, before_midnight)
    record_youtube_quota("videos", path, before_midnight)
    snapshot = youtube_quota_snapshot(path, before_midnight)
    assert (snapshot["search_used"], snapshot["data_used"]) == (1, 1)

    after_midnight = datetime(2026, 8, 26, 0, 1, tzinfo=pacific)
    reset = youtube_quota_snapshot(path, after_midnight)
    assert (reset["search_used"], reset["data_used"]) == (0, 0)
