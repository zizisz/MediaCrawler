import json
import os
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


PACIFIC = ZoneInfo("America/Los_Angeles")
QUOTA_FILE = Path(os.getenv("XDG_STATE_HOME", Path.home() / ".local/state")) / "mediacrawler" / "youtube_quota.json"


def _state(path: Path, now: datetime) -> dict:
    day = now.astimezone(PACIFIC).date().isoformat()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        state = {}
    if state.get("day") != day:
        return {"day": day, "search_used": 0, "data_used": 0}
    return state


def youtube_quota_snapshot(
    path: Path = QUOTA_FILE,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(PACIFIC)
    state = _state(path, now)
    search_limit = int(os.getenv("YOUTUBE_SEARCH_DAILY_QUOTA", "100"))
    data_limit = int(os.getenv("YOUTUBE_DAILY_QUOTA", "10000"))
    next_day = now.astimezone(PACIFIC).date() + timedelta(days=1)
    reset_at = datetime.combine(next_day, time.min, tzinfo=PACIFIC)
    search_used = int(state.get("search_used", 0))
    data_used = int(state.get("data_used", 0))
    return {
        "day": state["day"],
        "search_used": search_used,
        "search_limit": search_limit,
        "search_remaining": max(0, search_limit - search_used),
        "data_used": data_used,
        "data_limit": data_limit,
        "data_remaining": max(0, data_limit - data_used),
        "reset_at": reset_at.isoformat(),
        "timezone": "America/Los_Angeles",
        "estimated": True,
    }


def record_youtube_quota(
    endpoint: str,
    path: Path = QUOTA_FILE,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(PACIFIC)
    state = _state(path, now)
    key = "search_used" if endpoint == "search" else "data_used"
    state[key] = int(state.get(key, 0)) + 1
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    return youtube_quota_snapshot(path, now)
