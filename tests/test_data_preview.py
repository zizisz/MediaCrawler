import asyncio
import json

import pytest
from fastapi import HTTPException

import api.routers.data as data_router
from api.routers.data import RenameFileRequest


def test_preview_pages_and_searches_the_complete_file(tmp_path, monkeypatch):
    rows = [{"id": index, "text": "needle" if index == 137 else "plain"} for index in range(150)]
    (tmp_path / "rows.json").write_text(json.dumps(rows), encoding="utf-8")
    monkeypatch.setattr(data_router, "DATA_DIR", tmp_path)

    page = asyncio.run(data_router.get_file_content("rows.json", limit=50, offset=50, query=""))
    found = asyncio.run(data_router.get_file_content("rows.json", limit=50, offset=0, query="needle"))

    assert [page["data"][0]["id"], page["data"][-1]["id"]] == [50, 99]
    assert found == {"data": [rows[137]], "total": 1, "all_total": 150, "columns": None}


def test_rename_and_delete_one_managed_file(tmp_path, monkeypatch):
    source = tmp_path / "search_contents.json"
    source.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(data_router, "DATA_DIR", tmp_path)

    renamed = asyncio.run(data_router.rename_data_file(source.name, RenameFileRequest(name="PEEK leads")))
    assert renamed["file"]["name"] == "PEEK leads.json"
    assert asyncio.run(data_router.delete_data_file("PEEK leads.json")) == {"deleted": "PEEK leads.json"}
    assert not (tmp_path / "PEEK leads.json").exists()
    with pytest.raises(HTTPException, match="Access denied"):
        asyncio.run(data_router.delete_data_file("../outside.json"))
