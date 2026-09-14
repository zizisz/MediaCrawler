import asyncio
import csv
import io

import api.routers.ai as ai
import api.routers.data as data_router
from api.routers.ai import LeadUpdate, _is_moderation_error, _latest_search_data, _merge_lead, _normalize_intelligence, _normalize_leads, _response_text


def test_intelligence_csv_preserves_text_and_blocks_formulas(monkeypatch):
    monkeypatch.setattr(ai, "_read_intelligence", lambda: [{
        "title": 'PEEK,"新闻"\n第二行', "summary": "=1+1", "reliability_score": 0,
        "source_url": "https://example.test/news",
    }])

    async def read_export():
        response = await ai.export_intelligence()
        return b"".join([chunk async for chunk in response.body_iterator])

    content = asyncio.run(read_export())
    assert content.startswith(b"\xef\xbb\xbf")
    rows = list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
    assert len(rows) == 1
    assert rows[0]["情报标题"] == 'PEEK,"新闻"\n第二行'
    assert rows[0]["摘要"] == "'=1+1"
    assert rows[0]["可靠度(%)"] == "0"
    assert rows[0]["来源链接"] == "https://example.test/news"


def test_merge_lead_keeps_contact_and_combines_patents():
    old = {"company_name": "ACME", "email": "sales@acme.test", "patents": "EP1", "keywords": "PEEK", "source_platform": "Douyin", "company_info": "抖音旧资料", "evidence": "抖音旧证据", "potential_score": 75, "followed_up": True}
    new = {"company_name": "ACME", "email": "info@acme.test", "patents": "EP1; EP2", "keywords": "PEEK; implant", "source_platform": "国家知识产权局", "company_info": "联网新资料", "evidence": "联网新证据", "potential_score": 90}
    merged = _merge_lead(old, new)
    assert merged["email"] == "sales@acme.test; info@acme.test"
    assert merged["patents"] == "EP1; EP2"
    assert merged["keywords"] == "PEEK; implant"
    assert merged["source_platform"] == "Douyin; 国家知识产权局"
    assert merged["company_info"] == "抖音旧资料\n联网新资料"
    assert merged["evidence"] == "抖音旧证据\n联网新证据"
    assert merged["potential_score"] == 90
    assert merged["followed_up"] is True


def test_qwen_response_is_normalized():
    raw = _response_text({"choices": [{"message": {"content": "ok"}}]})
    leads = _normalize_leads([{"company_name": "ACME", "potential_score": "105", "source_urls": ["https://a.test", "https://b.test"]}])
    assert raw == "ok"
    assert leads[0]["potential_score"] == 100
    assert leads[0]["email"] == ""
    assert leads[0]["source_urls"] == "https://a.test; https://b.test"
    assert _is_moderation_error("Input text data may contain inappropriate content.")

    intelligence = _normalize_intelligence([{"title": "PEI expansion", "reliability_score": "105", "materials": "PEI"}])
    assert intelligence[0]["reliability_score"] == 100
    assert intelligence[0]["source_url"] == ""


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


def test_targeted_update_merges_full_name_and_duplicate(tmp_path, monkeypatch):
    monkeypatch.setattr(ai, "LEADS_FILE", tmp_path / "leads.json")
    ai._write_leads([
        {"id": "short", "company_name": "吉大特塑", "aliases": "", "followed_up": True, "created_at": "old"},
        {"id": "full", "company_name": "长春吉大特塑工程研究有限公司", "aliases": "吉大特塑", "website": "https://example.test"},
    ])
    incoming = _normalize_leads([{"company_name": "长春吉大特塑工程研究有限公司", "aliases": "吉大特塑", "phone": "123"}])
    assert asyncio.run(ai._update_target_lead("short", incoming)) == 1
    leads = ai._read_leads()
    assert len(leads) == 1
    assert leads[0]["id"] == "short"
    assert leads[0]["company_name"] == "长春吉大特塑工程研究有限公司"
    assert "吉大特塑" in leads[0]["aliases"]
    assert leads[0]["website"] == "https://example.test"
    assert leads[0]["phone"] == "123"
    assert leads[0]["followed_up"] is True


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



def test_similar_search_runs_in_background(monkeypatch):
    monkeypatch.setattr(ai, "_similar_task", None)
    monkeypatch.setattr(ai, "_batch_task", None)
    monkeypatch.setattr(ai, "_read_leads", lambda: [{"id": "1", "company_name": "ACME"}])
    monkeypatch.setattr(ai, "_secret", lambda *_: "key")

    async def fake_chat(request):
        assert "ACME" in request.message
        assert request.max_leads == 20
        return {"answer": "saved"}

    monkeypatch.setattr(ai, "chat", fake_chat)

    async def run():
        started = await ai.find_similar("1")
        assert started["status"] == "running"
        await ai._similar_task
        assert (await ai.similar_status())["status"] == "completed"

    asyncio.run(run())
