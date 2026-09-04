import asyncio
import json

import api.routers.ai as ai
import api.routers.data as data


def setup_files(tmp_path, monkeypatch, count=121):
    root = tmp_path / "data"
    root.mkdir()
    rows = [{"id": index, "text": f"PEEK record {index}"} for index in range(count)]
    (root / "records.json").write_text(json.dumps(rows))
    monkeypatch.setattr(ai, "DATA_DIR", root)
    monkeypatch.setattr(data, "DATA_DIR", root)
    for module in (ai, data):
        monkeypatch.setattr(module, "AI_DIR", root / "ai")
    for name, filename in [("LEADS_FILE", "leads.json"), ("INTEL_FILE", "intel.json"), ("CHAT_FILE", "chat.json"), ("USAGE_FILE", "usage.json"), ("BATCH_FILE", "batch.json")]:
        monkeypatch.setattr(ai, name, root / "ai" / filename)
    monkeypatch.setattr(data, "ANALYSIS_FILE", root / "ai" / "analyzed.json")
    monkeypatch.setattr(data, "REJECTED_FILE", root / "ai" / "rejected.json")
    monkeypatch.setattr(ai, "_batch_task", None)
    monkeypatch.setattr(ai, "_batch_stop", False)
    monkeypatch.setattr(ai, "_secret", lambda *_: "test-key")
    return rows


def job():
    return {"id": "test", "status": "running", "source_files": ["records.json"], "batches": 0}


def test_pending_reads_past_500_and_deduplicates(tmp_path, monkeypatch):
    rows = setup_files(tmp_path, monkeypatch, 620)
    data._write_analysis_ids({data._row_fingerprint(row) for row in rows[:500]})
    data._write_rejected_ids({data._row_fingerprint(rows[500])})
    records, _, ids = ai._latest_search_data("selected", 50, source_files=["records.json"], only_pending=True)
    assert len(ids) == 50
    assert records[0]["id"] == "501"
    assert ai._batch_counts(["records.json"]) == {"total": 620, "analyzed": 500, "skipped": 1, "remaining": 119}


def test_worker_finishes_all_and_resume_skips_saved(tmp_path, monkeypatch):
    setup_files(tmp_path, monkeypatch, 621)
    calls = []

    async def fake_chat(request):
        _, _, ids = ai._latest_search_data("selected", request.max_records, source_files=request.source_files, only_pending=True)
        calls.extend(ids)
        data._write_analysis_ids(data._read_analysis_ids() | set(ids))
        if len(calls) == 50:
            monkeypatch.setattr(ai, "_batch_stop", True)
        return {"records_used": len(ids), "records_skipped": 0}

    monkeypatch.setattr(ai, "chat", fake_chat)
    first = job()
    asyncio.run(ai._run_batch(first))
    assert first["status"] == "paused" and first["remaining"] == 571
    monkeypatch.setattr(ai, "_batch_stop", False)
    second = job()
    asyncio.run(ai._run_batch(second))
    assert second["status"] == "completed" and second["remaining"] == 0
    assert len(calls) == len(set(calls)) == 621


def test_long_text_is_not_truncated_and_batch_is_bounded(tmp_path, monkeypatch):
    setup_files(tmp_path, monkeypatch, 1)
    rows = [{"id": i, "text": "a" * 6000} for i in range(20)]
    (ai.DATA_DIR / "records.json").write_text(json.dumps(rows))
    records, _, _ = ai._latest_search_data("selected", 50, source_files=["records.json"], only_pending=True)
    assert 0 < len(records) < 20
    assert records[0]["text"] == "a" * 6000
    assert sum(len(json.dumps(row, ensure_ascii=False)) for row in records) <= 50_000


def test_worker_pauses_on_error_without_marking_records(tmp_path, monkeypatch):
    setup_files(tmp_path, monkeypatch)

    async def fail(_request):
        raise RuntimeError("network unavailable")

    monkeypatch.setattr(ai, "chat", fail)
    state = job()
    asyncio.run(ai._run_batch(state))
    assert state["status"] == "error"
    assert not data._read_analysis_ids()
    assert json.loads(ai.BATCH_FILE.read_text())["remaining"] == 121

    ai._write_batch({"status": "running"})
    assert asyncio.run(ai.batch_status())["status"] == "paused"


def test_moderation_is_persisted_separately(tmp_path, monkeypatch):
    setup_files(tmp_path, monkeypatch, 1)

    class Response:
        is_success = False
        reason_phrase = "Bad Request"

        def json(self):
            return {"error": {"message": "Input text may contain inappropriate content"}}

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def post(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(ai.httpx, "AsyncClient", Client)
    result = asyncio.run(ai.chat(ai.ChatRequest(message="分析", source_files=["records.json"], only_pending=True)))
    assert result["records_used"] == 0 and result["records_skipped"] == 1
    assert not data._read_analysis_ids()
    assert len(data._read_rejected_ids()) == 1
    assert ai._batch_counts(["records.json"])["remaining"] == 0


def test_material_focus_is_sent_to_model(tmp_path, monkeypatch):
    setup_files(tmp_path, monkeypatch, 1)
    captured = []

    class Response:
        is_success = True

        def json(self):
            return {"choices": [{"message": {"content": json.dumps({"answer": "ok", "leads": [], "intelligence": []})}}]}

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def post(self, *_args, **kwargs):
            captured.append(kwargs["json"]["messages"][0]["content"])
            return Response()

    monkeypatch.setattr(ai.httpx, "AsyncClient", Client)
    asyncio.run(ai.chat(ai.ChatRequest(message="分析", source_files=["records.json"], only_pending=True)))
    for material in ["PEEK CF30", "PEEK GF30", "PAI", "PI", "PSU", "PPSU", "PEI GF30", "PPS", "PFA", "PTFE", "POM"]:
        assert material in captured[0]
    assert "高性能工程塑料零件用户" in captured[0]
    assert "专利出现某材料不代表已量产或正在采购" in captured[0]
    assert "不要假定本厂能供应所有关注材料或零件" in captured[0]
