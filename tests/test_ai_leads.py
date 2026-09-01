import asyncio

import api.routers.ai as ai
import api.routers.data as data_router
from api.routers.ai import LeadUpdate, _force_web_search, _is_moderation_error, _latest_search_data, _merge_lead, _normalize_intelligence, _normalize_leads, _response_text


def test_merge_lead_keeps_contact_and_combines_patents():
    old = {"company_name": "ACME", "email": "sales@acme.test", "patents": "EP1", "keywords": "PEEK", "followed_up": True}
    new = {"company_name": "ACME", "email": "", "patents": "EP1; EP2", "keywords": "PEEK; implant"}
    merged = _merge_lead(old, new)
    assert merged["email"] == "sales@acme.test"
    assert merged["patents"] == "EP1; EP2"
    assert merged["keywords"] == "PEEK; implant"
    assert merged["followed_up"] is True


def test_qwen_response_is_normalized():
    raw = _response_text({"choices": [{"message": {"content": "ok"}}]})
    leads = _normalize_leads([{"company_name": "ACME", "potential_score": "105"}])
    assert raw == "ok"
    assert leads[0]["potential_score"] == 100
    assert leads[0]["email"] == ""
    assert _is_moderation_error("Input text data may contain inappropriate content.")

    intelligence = _normalize_intelligence([{"title": "PEI expansion", "reliability_score": "105", "materials": "PEI"}])
    assert intelligence[0]["reliability_score"] == 100
    assert intelligence[0]["source_url"] == ""
    assert _force_web_search("网上搜索补全企业资料")
    assert _force_web_search("补充一下这家公司的线索")
    assert not _force_web_search("解释这个专利是什么意思")


def test_history_and_followed_up_are_persisted(tmp_path, monkeypatch):
    monkeypatch.setattr(ai, "CHAT_FILE", tmp_path / "chat.json")
    monkeypatch.setattr(ai, "LEADS_FILE", tmp_path / "leads.json")
    monkeypatch.setattr(ai, "INTEL_FILE", tmp_path / "intel.json")
    monkeypatch.setattr(ai, "USAGE_FILE", tmp_path / "usage.json")
    ai._write_leads([{"id": "1", "company_name": "ACME", "followed_up": False}])

    asyncio.run(ai._append_history("问题", "回答"))
    assert asyncio.run(ai.clear_chat_history()) == {"deleted": 2}
    asyncio.run(ai.update_lead("1", LeadUpdate(followed_up=True)))
    asyncio.run(ai._record_usage({"prompt_tokens": 12, "completion_tokens": 3}))
    assert asyncio.run(ai._upsert_intelligence([{"title": "PEEK price", "event_date": "2026-09-01", "source_url": "https://example.test/1"}])) == 1
    assert asyncio.run(ai._upsert_intelligence([{"title": "PEEK price updated", "event_date": "2026-09-01", "source_url": "https://example.test/1"}])) == 1

    assert ai._read_history() == []
    assert ai._read_leads()[0]["followed_up"] is True
    assert ai._read_usage()["total_tokens"] == 15
    assert len(ai._read_intelligence()) == 1
    assert ai._read_intelligence()[0]["title"] == "PEEK price updated"


def test_douyin_alias_and_analysis_fingerprint(tmp_path, monkeypatch):
    folder = tmp_path / "douyin" / "json"
    folder.mkdir(parents=True)
    (folder / "DOUYIN_search_contents.json").write_text('[{"title":"PEEK need"}]', encoding="utf-8")
    monkeypatch.setattr(ai, "DATA_DIR", tmp_path)
    monkeypatch.setattr(data_router, "DATA_DIR", tmp_path)
    monkeypatch.setattr(data_router, "ANALYSIS_FILE", tmp_path / "ai" / "analyzed_records.json")
    monkeypatch.setattr(data_router, "AI_DIR", tmp_path / "ai")

    records, source, fingerprints = _latest_search_data("dy", 20)
    assert records[0]["title"] == "PEEK need"
    assert source.startswith("douyin/")
    data_router._write_analysis_ids(set(fingerprints))
    assert data_router._read_analysis_ids() == set(fingerprints)

    records, source, _ = _latest_search_data("selected", 20, source_files=["douyin/json/DOUYIN_search_contents.json"])
    assert len(records) == 1
    assert source.startswith("douyin/")
