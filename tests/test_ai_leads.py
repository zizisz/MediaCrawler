import asyncio

import api.routers.ai as ai
from api.routers.ai import LeadUpdate, _merge_lead, _normalize_leads, _response_text


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


def test_history_and_followed_up_are_persisted(tmp_path, monkeypatch):
    monkeypatch.setattr(ai, "CHAT_FILE", tmp_path / "chat.json")
    monkeypatch.setattr(ai, "LEADS_FILE", tmp_path / "leads.json")
    monkeypatch.setenv("AI_ACCESS_TOKEN", "test-token")
    ai._write_leads([{"id": "1", "company_name": "ACME", "followed_up": False}])

    asyncio.run(ai._append_history("问题", "回答"))
    asyncio.run(ai.update_lead("1", LeadUpdate(followed_up=True), "test-token"))

    assert ai._read_history()[-1]["content"] == "回答"
    assert ai._read_leads()[0]["followed_up"] is True
