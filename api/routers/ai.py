import asyncio
import csv
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .data import _read_analysis_ids, _row_fingerprint, _write_analysis_ids, resolve_managed_file, _read_rejected_ids, _write_rejected_ids


router = APIRouter(prefix="/ai", tags=["ai"])
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
AI_DIR = DATA_DIR / "ai"
LEADS_FILE = AI_DIR / "company_leads.json"
INTEL_FILE = AI_DIR / "market_intelligence.json"
CHAT_FILE = AI_DIR / "chat_history.json"
USAGE_FILE = AI_DIR / "qwen_usage.json"
MODEL = "qwen-flash"
DEFAULT_DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_lead_lock = asyncio.Lock()
_intel_lock = asyncio.Lock()
_chat_lock = asyncio.Lock()
_usage_lock = asyncio.Lock()
_analysis_lock = asyncio.Lock()
BATCH_FILE = AI_DIR / "analysis_batch.json"
_batch_task = None
_batch_stop = False
PLATFORM_DATA_DIRS = {"dy": "douyin", "wb": "weibo"}


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=12000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=12)
    platform: str = Field(default="epo", pattern=r"^[a-z0-9_-]{1,30}$")
    max_records: int = Field(default=100, ge=1, le=500)
    include_search_data: bool = False
    source_file: str = Field(default="", max_length=500)
    source_files: list[str] = Field(default_factory=list, max_length=20)
    record_indices: list[int] = Field(default_factory=list, max_length=500)
    target_lead_id: str = Field(default="", max_length=64)
    only_pending: bool = False


class LeadUpdate(BaseModel):
    followed_up: bool


def _secret(environment_name: str, file_name: str) -> str:
    value = os.getenv(environment_name, "").strip()
    if value:
        return value
    path = AI_DIR / file_name
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def _dashscope_base_url() -> str:
    return (_secret("DASHSCOPE_BASE_URL", "dashscope_base_url") or DEFAULT_DASHSCOPE_BASE_URL).rstrip("/")


def _read_leads() -> list[dict]:
    if not LEADS_FILE.exists():
        return []
    try:
        value = json.loads(LEADS_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _write_leads(leads: list[dict]):
    AI_DIR.mkdir(parents=True, exist_ok=True)
    temporary = LEADS_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(leads, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(LEADS_FILE)


def _read_intelligence() -> list[dict]:
    if not INTEL_FILE.exists():
        return []
    try:
        value = json.loads(INTEL_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _write_intelligence(items: list[dict]):
    AI_DIR.mkdir(parents=True, exist_ok=True)
    temporary = INTEL_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(INTEL_FILE)


def _read_history() -> list[dict]:
    if not CHAT_FILE.exists():
        return []
    try:
        value = json.loads(CHAT_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _write_history(messages: list[dict]):
    AI_DIR.mkdir(parents=True, exist_ok=True)
    temporary = CHAT_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(CHAT_FILE)


def _read_usage() -> dict:
    try:
        value = json.loads(USAGE_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


async def _record_usage(value: dict):
    input_tokens = int(value.get("prompt_tokens", value.get("input_tokens", 0)) or 0)
    output_tokens = int(value.get("completion_tokens", value.get("output_tokens", 0)) or 0)
    async with _usage_lock:
        usage = _read_usage()
        usage.setdefault("tracking_since", datetime.now(timezone.utc).isoformat())
        usage["calls"] = int(usage.get("calls", 0)) + 1
        usage["input_tokens"] = int(usage.get("input_tokens", 0)) + input_tokens
        usage["output_tokens"] = int(usage.get("output_tokens", 0)) + output_tokens
        usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
        AI_DIR.mkdir(parents=True, exist_ok=True)
        temporary = USAGE_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(usage, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(USAGE_FILE)


async def _append_history(question: str, answer: str):
    async with _chat_lock:
        messages = _read_history()
        now = datetime.now(timezone.utc).isoformat()
        messages.extend([
            {"role": "user", "content": question, "created_at": now},
            {"role": "assistant", "content": answer, "created_at": now},
        ])
        _write_history(messages)


def _merge_list_text(old: str, new: str) -> str:
    values = []
    for value in (old, new):
        values.extend(part.strip() for part in value.replace("；", ";").split(";") if part.strip())
    return "; ".join(dict.fromkeys(values))


def _merge_text(old: object, new: object) -> str:
    old_text, new_text = str(old or "").strip(), str(new or "").strip()
    if not old_text or old_text in new_text:
        return new_text
    if not new_text or new_text in old_text:
        return old_text
    return f"{old_text}\n{new_text}"


def _merge_lead(existing: dict, incoming: dict) -> dict:
    merged = dict(existing)
    for key, value in incoming.items():
        if key in {"aliases", "website", "email", "phone", "address", "contact_person", "patents", "patent_titles", "keywords", "source_platform", "source_urls"}:
            merged[key] = _merge_list_text(str(merged.get(key, "")), str(value or ""))
        elif key in {"company_info", "evidence", "next_action"}:
            merged[key] = _merge_text(merged.get(key), value)
        elif key == "potential_score":
            merged[key] = max(int(merged.get(key, 0) or 0), int(value or 0))
        elif key == "company_name" and value:
            old_name, new_name = str(merged.get(key, "")).strip(), str(value).strip()
            merged["company_name"] = max((old_name, new_name), key=len)
            shorter = min((old_name, new_name), key=len)
            if shorter and shorter != merged["company_name"]:
                merged["aliases"] = _merge_list_text(str(merged.get("aliases", "")), shorter)
        elif value not in (None, ""):
            merged[key] = value
    merged["updated_at"] = datetime.now(timezone.utc).isoformat()
    return merged


def _lead_names(lead: dict) -> set[str]:
    values = [str(lead.get("company_name", "")), *str(lead.get("aliases", "")).replace("；", ";").split(";")]
    return {value.strip().casefold() for value in values if value.strip()}


async def _update_target_lead(lead_id: str, incoming: list[dict]) -> int:
    async with _lead_lock:
        leads = _read_leads()
        target_index = next((index for index, lead in enumerate(leads) if lead.get("id") == lead_id), None)
        if target_index is None:
            raise HTTPException(status_code=404, detail="Lead not found")
        merged = leads[target_index]
        for lead in incoming:
            merged = _merge_lead(merged, lead)
        duplicate_indices = []
        for index, lead in enumerate(leads):
            if index != target_index and _lead_names(merged) & _lead_names(lead):
                merged = _merge_lead(merged, lead)
                duplicate_indices.append(index)
        merged.update({
            "id": lead_id,
            "followed_up": leads[target_index].get("followed_up", False),
            "created_at": leads[target_index].get("created_at", datetime.now(timezone.utc).isoformat()),
        })
        leads[target_index] = merged
        _write_leads([lead for index, lead in enumerate(leads) if index not in duplicate_indices])
        return 1 if incoming else 0


async def _upsert_leads(incoming: list[dict]) -> int:
    async with _lead_lock:
        leads = _read_leads()
        by_name = {name: index for index, item in enumerate(leads) for name in _lead_names(item)}
        changed = 0
        for lead in incoming:
            name = str(lead.get("company_name", "")).strip()
            if not name:
                continue
            matched_index = next((by_name[key] for key in _lead_names(lead) if key in by_name), None)
            if matched_index is not None:
                leads[matched_index] = _merge_lead(leads[matched_index], lead)
                for key in _lead_names(leads[matched_index]):
                    by_name[key] = matched_index
            else:
                now = datetime.now(timezone.utc).isoformat()
                lead.update({"id": uuid4().hex, "followed_up": False, "created_at": now, "updated_at": now})
                leads.append(lead)
                for key in _lead_names(lead):
                    by_name[key] = len(leads) - 1
            changed += 1
        _write_leads(leads)
        return changed


async def _upsert_intelligence(incoming: list[dict]) -> int:
    async with _intel_lock:
        items = _read_intelligence()
        by_key = {
            (str(item.get("source_url", "")).strip() or f'{item.get("title", "")}|{item.get("event_date", "")}').casefold(): index
            for index, item in enumerate(items)
        }
        changed = 0
        for item in incoming:
            key = (item.get("source_url") or f'{item.get("title", "")}|{item.get("event_date", "")}').strip().casefold()
            if not key:
                continue
            now = datetime.now(timezone.utc).isoformat()
            if key in by_key:
                item.update({"id": items[by_key[key]]["id"], "created_at": items[by_key[key]].get("created_at", now), "updated_at": now})
                items[by_key[key]] = item
            else:
                item.update({"id": uuid4().hex, "created_at": now, "updated_at": now})
                items.append(item)
                by_key[key] = len(items) - 1
            changed += 1
        _write_intelligence(items)
        return changed


def _load_records(path: Path) -> list[dict]:
    if path.suffix == ".json":
        value = json.loads(path.read_text(encoding="utf-8"))
        rows = value if isinstance(value, list) else [value]
    elif path.suffix == ".jsonl":
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    else:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    return [row for row in rows if isinstance(row, dict)]


def _latest_search_data(
    platform: str,
    limit: int,
    source_file: str = "",
    source_files: list[str] | None = None,
    record_indices: list[int] | None = None,
    only_pending: bool = False,
) -> tuple[list[dict], str, list[str]]:
    selected_files = list(dict.fromkeys(source_files or ([source_file] if source_file else [])))
    if selected_files:
        indexed_rows = []
        for selected_file in selected_files:
            path = resolve_managed_file(selected_file)
            rows = _load_records(path)
            wanted = record_indices if source_file and len(selected_files) == 1 else range(len(rows))
            indexed_rows.extend((path, index, rows[index]) for index in wanted if 0 <= index < len(rows))
        if only_pending:
            seen = _read_analysis_ids() | _read_rejected_ids()
            pending = []
            for entry in indexed_rows:
                fingerprint = _row_fingerprint(entry[2])
                if fingerprint not in seen:
                    pending.append(entry)
                    seen.add(fingerprint)
            indexed_rows = pending
        indexed_rows = indexed_rows[:limit]
        source_name = ", ".join(selected_files)
    else:
        platform_dir = DATA_DIR / PLATFORM_DATA_DIRS.get(platform, platform)
        candidates = [
            path for extension in ("json", "jsonl", "csv")
            for path in platform_dir.glob(f"{extension}/*contents*.{extension}")
            if path.is_file()
        ]
        if not candidates:
            return [], "", []
        latest = max(candidates, key=lambda path: path.stat().st_mtime)
        rows = _load_records(latest)
        indexed_rows = [(latest, index, row) for index, row in list(enumerate(rows))[-limit:]]
        source_name = str(latest.relative_to(DATA_DIR))
    compact = []
    used_chars = 0
    for path, index, row in (indexed_rows if only_pending else reversed(indexed_rows)):
        item = {"__source_file": str(path.relative_to(DATA_DIR)), "__source_index": index}
        for key, value in row.items():
            if value in (None, "", [], {}):
                continue
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
            item[str(key)] = text if only_pending else text[:2500]
        size = len(json.dumps(item, ensure_ascii=False))
        char_limit = 50_000 if only_pending else 350_000
        if only_pending and size > char_limit:
            if compact:
                break
            raise HTTPException(status_code=400, detail=f"{path.name} 第 {index + 1} 条超过 50000 字符，请单独处理；本条未标记为已分析")
        if compact and used_chars + size > char_limit:
            break
        compact.append((item, _row_fingerprint(row)))
        used_chars += size
    if not only_pending:
        compact.reverse()
    return [item for item, _ in compact], source_name, [fingerprint for _, fingerprint in compact]


def _response_text(payload: dict) -> str:
    choices = payload.get("choices", [])
    return choices[0].get("message", {}).get("content", "") if choices else ""


def _is_moderation_error(detail: str) -> bool:
    value = detail.casefold()
    return "inappropriate content" in value or "data_inspection_failed" in value


def _lead_context(message: str) -> list[dict]:
    leads = _read_leads()
    text = message.casefold()
    matched = [lead for lead in leads if str(lead.get("company_name", "")).strip().casefold() in text]
    return (matched or leads[-20:])[:20]


LEAD_DEFAULTS = {
    "company_name": "", "aliases": "", "company_info": "", "country": "", "website": "", "email": "",
    "phone": "", "address": "", "contact_person": "", "patents": "", "patent_titles": "",
    "keywords": "", "source_platform": "", "source_urls": "", "evidence": "",
    "potential_score": 0, "next_action": "",
}

INTEL_DEFAULTS = {
    "title": "", "summary": "", "event_date": "", "materials": "", "source_platform": "",
    "source_url": "", "evidence": "", "analysis": "", "reliability_score": 0,
    "reliability_reason": "", "impact": "", "next_action": "",
}


def _normalize_leads(value) -> list[dict]:
    normalized = []
    for item in value[:50] if isinstance(value, list) else []:
        if not isinstance(item, dict) or not str(item.get("company_name", "")).strip():
            continue
        lead = {key: item.get(key, default) for key, default in LEAD_DEFAULTS.items()}
        try:
            lead["potential_score"] = max(0, min(100, int(lead["potential_score"])))
        except (TypeError, ValueError):
            lead["potential_score"] = 0
        for key in LEAD_DEFAULTS.keys() - {"potential_score"}:
            lead[key] = "; ".join(map(str, lead[key])) if isinstance(lead[key], list) else str(lead[key] or "")
        normalized.append(lead)
    return normalized


def _normalize_intelligence(value) -> list[dict]:
    normalized = []
    for item in value[:50] if isinstance(value, list) else []:
        if not isinstance(item, dict) or not str(item.get("title", "")).strip():
            continue
        intel = {key: item.get(key, default) for key, default in INTEL_DEFAULTS.items()}
        try:
            intel["reliability_score"] = max(0, min(100, int(intel["reliability_score"])))
        except (TypeError, ValueError):
            intel["reliability_score"] = 0
        for key in INTEL_DEFAULTS.keys() - {"reliability_score"}:
            intel[key] = str(intel[key] or "")
        normalized.append(intel)
    return normalized


@router.get("/status")
async def ai_status():
    return {
        "model": MODEL,
        "api_configured": bool(_secret("DASHSCOPE_API_KEY", "dashscope_api_key")),
        "access_configured": True,
        "usage": _read_usage(),
    }


@router.post("/chat")
async def chat(request: ChatRequest):
    if _batch_task and not _batch_task.done() and asyncio.current_task() is not _batch_task:
        raise HTTPException(status_code=409, detail="后台正在分批分析，请完成或停止后再发送")
    api_key = _secret("DASHSCOPE_API_KEY", "dashscope_api_key")
    if not api_key:
        raise HTTPException(status_code=503, detail="DASHSCOPE_API_KEY is not configured on the server")

    data_mode = request.include_search_data or bool(request.source_file or request.source_files)
    records, source_file, fingerprints = _latest_search_data(
        request.platform,
        min(request.max_records, 20) if request.platform == "x" else request.max_records,
        request.source_file,
        request.source_files,
        request.record_indices,
        request.only_pending,
    ) if data_mode else ([], "", [])
    if request.only_pending and not records:
        return {"answer": "没有待分析记录", "records_used": 0, "records_skipped": 0}
    if (request.source_file or request.source_files) and not records:
        raise HTTPException(status_code=400, detail="没有找到所选记录，请重新打开数据预览后选择")
    base_messages = [{
        "role": "system",
        "content": (
            "你是B2B潜客与行业情报分析助手，重点关注PEEK、PEI、PSU及其玻纤、碳纤、耐磨、导电等改性材料。"
            "除非用户明确询问本公司，否则不要在回答中宣传或反复介绍聚泰新材料。"
            "根据用户问题和搜索记录，同步判断潜在采购企业，并提取与这些材料有关的供需变化、价格、扩产、停产、认证、技术、应用、竞品和市场传闻。"
            "证据不足时明确说明，不得编造企业、联系方式、专利或结论。联系方式仅可使用输入记录中明确出现的内容；没有就返回空字符串。"
            "使用联网搜索时，必须把实际找到的公开网页链接写入source_urls或source_url，并在证据中说明来自哪个网页；没有可靠网页就明确写未找到。"
            "合并同一企业的多条专利或记录，potential_score按0-100评估采购相关性，并给出简短下一步。"
            "情报可靠度reliability_score按0-100评估；明确区分事实、推测和传闻。日期只能使用输入中可验证的日期，未知就留空。"
            "只返回JSON对象，必须包含answer、leads和intelligence；answer用中文，两类结果各最多50条。"
            "每条leads必须含这些字段：company_name, aliases, company_info, country, website, email, phone, address, "
            "company_name使用可验证的企业全称，aliases填写简称、旧称或常用名并用分号分隔。"
            "contact_person, patents, patent_titles, keywords, source_platform, source_urls, evidence, potential_score, next_action。"
            "每条intelligence必须含这些字段：title, summary, event_date, materials, source_platform, source_url, evidence, "
            "analysis, reliability_score, reliability_reason, impact, next_action。"
        ),
    }, *[
        message.model_dump() for message in request.history[-8:]
        if not message.content.startswith(("分析失败：", "连接失败："))
    ]]

    async def analyze(client: httpx.AsyncClient, batch: list[dict]) -> dict:
        context_label = "所选/最新搜索数据" if data_mode else "企业线索库现有资料"
        context = batch if data_mode else _lead_context(request.message)
        payload = {
            "model": MODEL,
            "messages": [*base_messages, {
                "role": "user",
                "content": request.message + f"\n\n{context_label}：\n" + json.dumps(context, ensure_ascii=False),
            }],
            "response_format": {"type": "json_object"},
            "enable_thinking": False,
            "max_completion_tokens": 8000,
        }
        if not data_mode:
            payload["enable_search"] = True
            payload["search_options"] = {"search_strategy": "turbo", "forced_search": True}
        response = await client.post(
            f"{_dashscope_base_url()}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        if not response.is_success:
            try:
                detail = response.json().get("error", {}).get("message", response.reason_phrase)
            except ValueError:
                detail = response.reason_phrase
            if _is_moderation_error(detail):
                raise ValueError("moderation")
            raise HTTPException(status_code=502, detail=f"千问 API error: {detail}")
        body = response.json()
        await _record_usage(body.get("usage", {}))
        try:
            return json.loads(_response_text(body))
        except json.JSONDecodeError:
            raise HTTPException(status_code=502, detail="千问返回了无效的 JSON 响应")

    skipped = 0
    rejected_fingerprints = []
    async with httpx.AsyncClient(trust_env=False, timeout=120.0) as client:
        try:
            results = [await analyze(client, records)]
            analyzed_fingerprints = fingerprints
        except ValueError:
            results = []
            analyzed_fingerprints = []
            for start in range(0, len(records), 5):
                batch = records[start:start + 5]
                batch_fingerprints = fingerprints[start:start + 5]
                try:
                    results.append(await analyze(client, batch))
                    analyzed_fingerprints.extend(batch_fingerprints)
                except ValueError:
                    for row, fingerprint in zip(batch, batch_fingerprints):
                        try:
                            results.append(await analyze(client, [row]))
                            analyzed_fingerprints.append(fingerprint)
                        except ValueError:
                            skipped += 1
                            rejected_fingerprints.append(fingerprint)
    if not results and not request.only_pending:
        raise HTTPException(status_code=422, detail="最新搜索数据全部触发内容审核，未发送给模型分析")

    leads = _normalize_leads([lead for result in results for lead in result.get("leads", [])])
    intelligence = _normalize_intelligence([item for result in results for item in result.get("intelligence", [])])
    saved = await _update_target_lead(request.target_lead_id, leads) if request.target_lead_id else await _upsert_leads(leads)
    intel_saved = await _upsert_intelligence(intelligence)
    if analyzed_fingerprints or rejected_fingerprints:
        async with _analysis_lock:
            analyzed_ids = _read_analysis_ids()
            analyzed_ids.update(analyzed_fingerprints)
            _write_analysis_ids(analyzed_ids)
            if rejected_fingerprints:
                _write_rejected_ids(_read_rejected_ids() | set(rejected_fingerprints))
    answer = results[0].get("answer", "") if len(results) == 1 else f"已完成分批分析，提取出 {len(leads)} 家企业线索和 {len(intelligence)} 条行业情报。"
    assistant_content = answer + (f"\n\n已读取 {len(records) - skipped} 条记录"
        f"{'（' + source_file + '）' if source_file else ''}，保存/更新 {saved} 家企业线索和 {intel_saved} 条行业情报。"
        f"{' 因内容审核跳过 ' + str(skipped) + ' 条记录。' if skipped else ''}"
        if data_mode else f"\n\n已使用企业线索库资料并强制请求联网搜索，保存/更新 {saved} 家企业线索和 {intel_saved} 条行业情报。")
    await _append_history(request.message, assistant_content)
    return {
        "answer": assistant_content,
        "leads_saved": saved,
        "intelligence_saved": intel_saved,
        "records_used": len(records) - skipped,
        "records_skipped": skipped,
        "source_file": source_file,
    }


class BatchRequest(BaseModel):
    source_files: list[str] = Field(default_factory=list, max_length=20)
    platform: str = Field(default="selected", pattern=r"^[a-z0-9_-]{1,30}$")


def _write_batch(job):
    AI_DIR.mkdir(parents=True, exist_ok=True)
    temporary = BATCH_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    temporary.replace(BATCH_FILE)


def _batch_counts(paths):
    ids = set()
    for name in paths:
        path = resolve_managed_file(name)
        if path.suffix not in {".json", ".csv", ".jsonl"}:
            raise HTTPException(status_code=400, detail="分批分析仅支持 JSON / CSV 文件")
        ids.update(_row_fingerprint(row) for row in _load_records(path))
    analyzed = ids & _read_analysis_ids()
    rejected = (ids & _read_rejected_ids()) - analyzed
    return {"total": len(ids), "analyzed": len(analyzed), "skipped": len(rejected), "remaining": len(ids - analyzed - rejected)}


async def _run_batch(job):
    try:
        while not _batch_stop:
            job.update(_batch_counts(job["source_files"]))
            if not job["remaining"]:
                job["status"] = "completed"
                break
            job["message"] = f"正在分析第 {job['batches'] + 1} 批（每批最多 50 条）"
            _write_batch(job)
            result = await chat(ChatRequest(
                message=f"第 {job['batches'] + 1} 批：分析以下全部记录，筛选PEEK、PEI、PSU及改性材料企业线索与行业情报，标明来源、日期、可靠度。",
                platform="selected", source_files=job["source_files"], max_records=50, only_pending=True,
            ))
            if not result["records_used"] and not result["records_skipped"]:
                raise RuntimeError("本批未取得进展，已暂停，避免重复消耗额度")
            job["batches"] += 1
            job.update(_batch_counts(job["source_files"]))
            job["status"] = "stopping" if _batch_stop else "running"
            _write_batch(job)
        else:
            job["status"] = "paused"
        job["message"] = ("全部待分析记录已处理" if job["status"] == "completed" else "已停止；重新勾选文件可继续")
        job["message"] += f"：已分析 {job['analyzed']}/{job['total']}，审核跳过 {job['skipped']}，剩余 {job['remaining']}。"
    except asyncio.CancelledError:
        job.update(status="paused", message="服务中断，已保存完成批次；重新勾选文件可继续")
    except Exception as error:
        detail = error.detail if isinstance(error, HTTPException) else str(error)
        job.update(status="error", message=f"分批分析暂停：{detail}。已完成批次保留，重新勾选文件可继续。")
    finally:
        _write_batch(job)


@router.get("/analysis/status")
async def batch_status():
    if not BATCH_FILE.exists():
        return {"status": "idle"}
    job = json.loads(BATCH_FILE.read_text(encoding="utf-8"))
    if job["status"] in {"running", "stopping"} and (_batch_task is None or _batch_task.done()):
        job.update(status="paused", message="任务已中断，完成批次已保存；重新勾选文件可继续")
    return job


@router.post("/analysis/start")
async def start_batch(request: BatchRequest):
    global _batch_task, _batch_stop
    # ponytail: one background job for this single-user service; use a durable queue for multiple workers.
    async with _analysis_lock:
        if _batch_task and not _batch_task.done():
            raise HTTPException(status_code=409, detail="已有分批分析任务，请等待或停止")
        if not _secret("DASHSCOPE_API_KEY", "dashscope_api_key"):
            raise HTTPException(status_code=503, detail="服务器尚未配置千问密钥")
        paths = list(dict.fromkeys(request.source_files))
        if not paths:
            _, latest, _ = _latest_search_data(request.platform, 1)
            if not latest:
                raise HTTPException(status_code=400, detail="当前平台没有搜索结果，请先抓取或在数据浏览器勾选文件")
            paths = [latest]
        job = {"id": uuid4().hex, "status": "running", "source_files": paths, "batches": 0, "message": "已接收手动分析任务，正在分批处理", **_batch_counts(paths)}
        _batch_stop = False
        _write_batch(job)
        await _append_history("手动分批分析：" + ", ".join(paths), f"已接收 {len(paths)} 个文件，待分析 {job['remaining']} 条（去重后）；每批最多 50 条，自动跳过已分析和审核未通过的记录。")
        _batch_task = asyncio.create_task(_run_batch(job))
        return job


@router.post("/analysis/stop")
async def stop_batch():
    global _batch_stop
    _batch_stop = True
    job = await batch_status()
    if job["status"] == "running":
        job.update(status="stopping", message="正在停止：等待当前批次保存，不再启动下一批")
        _write_batch(job)
    return job


@router.get("/history")
async def chat_history():
    return {"messages": _read_history()}


@router.delete("/history")
async def clear_chat_history():
    async with _chat_lock:
        deleted = len(_read_history())
        _write_history([])
    return {"deleted": deleted}


@router.get("/leads")
async def list_leads():
    return {"leads": sorted(_read_leads(), key=lambda item: item.get("updated_at", ""), reverse=True)}


@router.get("/intelligence")
async def list_intelligence():
    return {"items": sorted(_read_intelligence(), key=lambda item: item.get("updated_at", ""), reverse=True)}


@router.delete("/intelligence/{item_id}")
async def delete_intelligence(item_id: str):
    async with _intel_lock:
        items = _read_intelligence()
        remaining = [item for item in items if item.get("id") != item_id]
        if len(remaining) == len(items):
            raise HTTPException(status_code=404, detail="Intelligence item not found")
        _write_intelligence(remaining)
    return {"deleted": item_id}


@router.delete("/leads/{lead_id}")
async def delete_lead(lead_id: str):
    async with _lead_lock:
        leads = _read_leads()
        remaining = [lead for lead in leads if lead.get("id") != lead_id]
        if len(remaining) == len(leads):
            raise HTTPException(status_code=404, detail="Lead not found")
        _write_leads(remaining)
    return {"deleted": lead_id}


@router.patch("/leads/{lead_id}")
async def update_lead(lead_id: str, request: LeadUpdate):
    async with _lead_lock:
        leads = _read_leads()
        for lead in leads:
            if lead.get("id") == lead_id:
                lead["followed_up"] = request.followed_up
                lead["updated_at"] = datetime.now(timezone.utc).isoformat()
                _write_leads(leads)
                return {"lead": lead}
    raise HTTPException(status_code=404, detail="Lead not found")


@router.get("/leads/export")
async def export_leads():
    leads = _read_leads()
    fields = [
        "company_name", "aliases", "company_info", "country", "website", "email", "phone", "address",
        "contact_person", "patents", "patent_titles", "keywords", "source_platform", "source_urls",
        "evidence", "potential_score", "next_action", "followed_up", "created_at", "updated_at",
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(leads)
    data = ("\ufeff" + output.getvalue()).encode("utf-8")
    return StreamingResponse(
        iter([data]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=company_leads.csv"},
    )


@router.get("/intelligence/export")
async def export_intelligence():
    fields = {
        "event_date": "消息日期", "materials": "材料", "title": "情报标题",
        "summary": "摘要", "analysis": "AI分析", "evidence": "证据",
        "reliability_score": "可靠度(%)", "reliability_reason": "可靠度依据",
        "impact": "影响", "next_action": "建议", "source_platform": "来源平台",
        "source_url": "来源链接", "created_at": "收集时间", "updated_at": "更新时间",
    }
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(fields.values())
    for item in _read_intelligence():
        values = [str(item.get(key) or "") if item.get(key) != 0 else "0" for key in fields]
        # Treat scraped text as text, never as an Excel formula.
        writer.writerow(["'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value for value in values])
    return StreamingResponse(
        iter([("\ufeff" + output.getvalue()).encode("utf-8")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=market_intelligence.csv"},
    )
