import pytest

from api.routers import data


@pytest.mark.asyncio
async def test_delete_all_data_files_only_deletes_managed_files(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "DATA_DIR", tmp_path)
    (tmp_path / "xhs" / "json").mkdir(parents=True)
    managed = [
        tmp_path / "xhs" / "json" / "search_comments.json",
        tmp_path / "xhs" / "json" / "search_contents.csv",
    ]
    for file_path in managed:
        file_path.write_text("[]", encoding="utf-8")
    config_file = tmp_path / "config.json.bak"
    config_file.write_text("keep", encoding="utf-8")

    result = await data.delete_all_data_files()

    assert result == {"deleted": 2}
    assert all(not file_path.exists() for file_path in managed)
    assert config_file.read_text(encoding="utf-8") == "keep"
