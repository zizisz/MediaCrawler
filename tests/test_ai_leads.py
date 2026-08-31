from api.routers.ai import _merge_lead, _normalize_leads, _response_text


def test_merge_lead_keeps_contact_and_combines_patents():
    old = {"company_name": "ACME", "email": "sales@acme.test", "patents": "EP1", "keywords": "PEEK"}
    new = {"company_name": "ACME", "email": "", "patents": "EP1; EP2", "keywords": "PEEK; implant"}
    merged = _merge_lead(old, new)
    assert merged["email"] == "sales@acme.test"
    assert merged["patents"] == "EP1; EP2"
    assert merged["keywords"] == "PEEK; implant"


def test_qwen_response_is_normalized():
    raw = _response_text({"choices": [{"message": {"content": "ok"}}]})
    leads = _normalize_leads([{"company_name": "ACME", "potential_score": "105"}])
    assert raw == "ok"
    assert leads[0]["potential_score"] == 100
    assert leads[0]["email"] == ""
