import asyncio
import csv
import hmac
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

import httpx
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field


router = APIRouter(prefix="/ai", tags=["ai"])
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
AI_DIR = DATA_DIR / "ai"
LEADS_FILE = AI_DIR / "company_leads.json"
CHAT_FILE = AI_DIR / "chat_history.json"
MODEL = "qwen-flash"
DEFAULT_DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_lead_lock = asyncio.Lock()
_chat_lock = asyncio.Lock()


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=12000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=12)
    platform: str = Field(default="epo", pattern=r"^[a-z0-9_-]{1,30}$")
    max_records: int = Field(default=100, ge=1, le=500)


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


def _authorize(token: str | None):
    expected = _secret("AI_ACCESS_TOKEN", "access_token")
    if not expected:
        raise HTTPException(status_code=503, detail="AI access protection is not configured")
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="AI access password is incorrect")


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


def _merge_lead(existing: dict, incoming: dict) -> dict:
    merged = dict(existing)
    for key, value in incoming.items():
        if key in {"patents", "patent_titles", "keywords", "source_urls"}:
            merged[key] = _merge_list_text(str(merged.get(key, "")), str(value or ""))
        elif value not in (None, ""):
            merged[key] = value
    merged["updated_at"] = datetime.now(timezone.utc).isoformat()
    return merged


async def _upsert_leads(incoming: list[dict]) -> int:
    async with _lead_lock:
        leads = _read_leads()
        by_name = {str(item.get("company_name", "")).strip().casefold(): index for index, item in enumerate(leads)}
        changed = 0
        for lead in incoming:
            name = str(lead.get("company_name", "")).strip()
            if not name:
                continue
            key = name.casefold()
            if key in by_name:
                leads[by_name[key]] = _merge_lead(leads[by_name[key]], lead)
            else:
                now = datetime.now(timezone.utc).isoformat()
                lead.update({"id": uuid4().hex, "followed_up": False, "created_at": now, "updated_at": now})
                leads.append(lead)
                by_name[key] = len(leads) - 1
            changed += 1
        _write_leads(leads)
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


def _latest_search_data(platform: str, limit: int) -> tuple[list[dict], str]:
    platform_dir = DATA_DIR / platform
    candidates = [
        path for extension in ("json", "jsonl", "csv")
        for path in platform_dir.glob(f"{extension}/*contents*.{extension}")
        if path.is_file()
    ]
    if not candidates:
        return [], ""
    latest = max(candidates, key=lambda path: path.stat().st_mtime)
    rows = _load_records(latest)[-limit:]
    compact = []
    used_chars = 0
    for row in reversed(rows):
        item = {}
        for key, value in row.items():
            if value in (None, "", [], {}):
                continue
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
            item[str(key)] = text[:2500]
        size = len(json.dumps(item, ensure_ascii=False))
        if compact and used_chars + size > 350_000:
            break
        compact.append(item)
        used_chars += size
    compact.reverse()
    return compact, str(latest.relative_to(DATA_DIR))


def _response_text(payload: dict) -> str:
    choices = payload.get("choices", [])
    return choices[0].get("message", {}).get("content", "") if choices else ""


def _is_moderation_error(detail: str) -> bool:
    value = detail.casefold()
    return "inappropriate content" in value or "data_inspection_failed" in value


LEAD_DEFAULTS = {
    "company_name": "", "company_info": "", "country": "", "website": "", "email": "",
    "phone": "", "address": "", "contact_person": "", "patents": "", "patent_titles": "",
    "keywords": "", "source_platform": "", "source_urls": "", "evidence": "",
    "potential_score": 0, "next_action": "",
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
            lead[key] = str(lead[key] or "")
        normalized.append(lead)
    return normalized


@router.get("/status")
async def ai_status():
    return {
        "model": MODEL,
        "api_configured": bool(_secret("DASHSCOPE_API_KEY", "dashscope_api_key")),
        "access_configured": bool(_secret("AI_ACCESS_TOKEN", "access_token")),
    }


@router.post("/chat")
async def chat(request: ChatRequest, x_ai_access_token: str | None = Header(default=None)):
    _authorize(x_ai_access_token)
    api_key = _secret("DASHSCOPE_API_KEY", "dashscope_api_key")
    if not api_key:
        raise HTTPException(status_code=503, detail="DASHSCOPE_API_KEY is not configured on the server")

    records, source_file = _latest_search_data(request.platform, request.max_records)
    base_messages = [{
        "role": "system",
        "content": (
            "你是聚泰新材料的B2B潜客分析助手。根据用户问题和搜索记录，判断哪些企业可能采购或使用PEEK等工程塑料。"
            "证据不足时明确说明，不得编造企业、联系方式、专利或结论。联系方式仅可使用输入记录中明确出现的内容；没有就返回空字符串。"
            "合并同一企业的多条专利或记录，potential_score按0-100评估采购相关性，并给出简短下一步。"
            "只返回JSON对象，必须包含answer和leads；answer用中文，leads最多50家且只保留有明确企业名称和证据的线索。"
            "每条leads必须含这些字段：company_name, company_info, country, website, email, phone, address, "
            "contact_person, patents, patent_titles, keywords, source_platform, source_urls, evidence, potential_score, next_action。"
        ),
    }, *[message.model_dump() for message in request.history[-8:]]]

    async def analyze(client: httpx.AsyncClient, batch: list[dict]) -> dict:
        payload = {
            "model": MODEL,
            "messages": [*base_messages, {
                "role": "user",
                "content": request.message + "\n\n最新搜索数据：\n" + json.dumps(batch, ensure_ascii=False),
            }],
            "response_format": {"type": "json_object"},
            "enable_thinking": False,
            "max_completion_tokens": 8000,
        }
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
        try:
            return json.loads(_response_text(response.json()))
        except json.JSONDecodeError:
            raise HTTPException(status_code=502, detail="千问返回了无效的 JSON 响应")

    skipped = 0
    async with httpx.AsyncClient(trust_env=False, timeout=120.0) as client:
        try:
            results = [await analyze(client, records)]
        except ValueError:
            results = []
            for start in range(0, len(records), 5):
                batch = records[start:start + 5]
                try:
                    results.append(await analyze(client, batch))
                except ValueError:
                    for row in batch:
                        try:
                            results.append(await analyze(client, [row]))
                        except ValueError:
                            skipped += 1
    if not results:
        raise HTTPException(status_code=422, detail="最新搜索数据全部触发内容审核，未发送给模型分析")

    leads = _normalize_leads([lead for result in results for lead in result.get("leads", [])])
    saved = await _upsert_leads(leads)
    answer = results[0].get("answer", "") if len(results) == 1 else f"已完成分批分析，提取出 {len(leads)} 家企业线索。"
    assistant_content = answer + (
        f"\n\n已读取 {len(records) - skipped} 条记录"
        f"{'（' + source_file + '）' if source_file else ''}，保存/更新 {saved} 家企业线索。"
        f"{' 因内容审核跳过 ' + str(skipped) + ' 条记录。' if skipped else ''}"
    )
    await _append_history(request.message, assistant_content)
    return {
        "answer": assistant_content,
        "leads_saved": saved,
        "records_used": len(records) - skipped,
        "source_file": source_file,
    }


@router.get("/history")
async def chat_history(x_ai_access_token: str | None = Header(default=None)):
    _authorize(x_ai_access_token)
    return {"messages": _read_history()}


@router.get("/leads")
async def list_leads(x_ai_access_token: str | None = Header(default=None)):
    _authorize(x_ai_access_token)
    return {"leads": sorted(_read_leads(), key=lambda item: item.get("updated_at", ""), reverse=True)}


@router.delete("/leads/{lead_id}")
async def delete_lead(lead_id: str, x_ai_access_token: str | None = Header(default=None)):
    _authorize(x_ai_access_token)
    async with _lead_lock:
        leads = _read_leads()
        remaining = [lead for lead in leads if lead.get("id") != lead_id]
        if len(remaining) == len(leads):
            raise HTTPException(status_code=404, detail="Lead not found")
        _write_leads(remaining)
    return {"deleted": lead_id}


@router.patch("/leads/{lead_id}")
async def update_lead(lead_id: str, request: LeadUpdate, x_ai_access_token: str | None = Header(default=None)):
    _authorize(x_ai_access_token)
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
async def export_leads(x_ai_access_token: str | None = Header(default=None)):
    _authorize(x_ai_access_token)
    leads = _read_leads()
    fields = [
        "company_name", "company_info", "country", "website", "email", "phone", "address",
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
