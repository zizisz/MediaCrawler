import asyncio
import json

import api.routers.data as data_router


def test_preview_pages_and_searches_the_complete_file(tmp_path, monkeypatch):
    rows = [{"id": index, "text": "needle" if index == 137 else "plain"} for index in range(150)]
    (tmp_path / "rows.json").write_text(json.dumps(rows), encoding="utf-8")
    monkeypatch.setattr(data_router, "DATA_DIR", tmp_path)

    page = asyncio.run(data_router.get_file_content("rows.json", limit=50, offset=50, query=""))
    found = asyncio.run(data_router.get_file_content("rows.json", limit=50, offset=0, query="needle"))

    assert [page["data"][0]["id"], page["data"][-1]["id"]] == [50, 99]
    assert found == {"data": [rows[137]], "total": 1, "all_total": 150, "columns": None}
