import config
from tools.async_file_writer import AsyncFileWriter
from tools.utils import utils


def test_data_file_name_starts_with_platform(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SAVE_DATA_PATH", str(tmp_path))
    monkeypatch.setattr(config, "ENABLE_GET_WORDCLOUD", False)
    monkeypatch.setattr(utils, "get_current_date", lambda: "2026-08-27")

    path = AsyncFileWriter("x", "search")._get_file_path("json", "contents")

    assert path.endswith("/x/json/X_search_contents_2026-08-27.json")
