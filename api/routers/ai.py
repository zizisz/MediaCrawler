import asyncio
import csv
import io
import imaplib
import json
import os
import re
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo
from uuid import uuid4

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .data import _read_analysis_ids, _row_fingerprint, _write_analysis_ids, resolve_managed_file, _read_rejected_ids, _write_rejected_ids
from ..services import crawler_manager
from ..services.linkedin import company_url, fetch_company, lead_fields


router = APIRouter(prefix="/ai", tags=["ai"])
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
AI_DIR = DATA_DIR / "ai"
LEADS_FILE = AI_DIR / "company_leads.json"
INTEL_FILE = AI_DIR / "market_intelligence.json"
CHAT_FILE = AI_DIR / "chat_history.json"
USAGE_FILE = AI_DIR / "qwen_usage.json"
MODEL = "qwen-flash"
MATERIAL_SCOPE = "PEEK、PEEK CF30、PEEK GF30、PAI、PI、PSU、PPSU、PEI、PEI GF30、PPS、PFA、PTFE、POM及相关改性材料"
CUSTOMER_FOCUS = (
    f"你的目标是识别高性能工程塑料零件用户，而不是仅寻找PEEK客户。关注材料范围：{MATERIAL_SCOPE}。"
    "这是业务关注范围，不要将其中所有材料一概归为同一性能等级。"
    "不要求企业必须使用PEEK；使用其他关注材料的零件也可构成线索。"
    "结合上下文识别材料、牌号及中英文写法；保留CF30、GF30等具体牌号，不能把普通材料推断成增强牌号。"
    "PI、PPS、POM等缩写以及peek等普通单词可能无关，必须依据塑料、零件或应用上下文判定。"
    "区分终端零件用户/设备制造商、零件加工商、贸易商、材料生产商及身份待核实；仅提及材料不等于采购。"
    "在company_info说明企业角色、实际使用或生产的零件、应用行业；keywords记录有证据的材料牌号、零件和应用。"
    "重点识别轴承、轴套、密封件、阀座、绝缘件、齿轮、耐磨件等零件的使用场景，不局限于这些例子。"
    "在evidence区分已验证事实、原文提及和待核实推测，并保留来源；专利出现某材料不代表已量产或正在采购。"
    "potential_score按0-100评估作为零件应用客户的相关性与证据强度，不是成交概率；"
    "实际应用明确的终端用户/设备制造商优先，加工商可作潜客；不能仅因供应商或贸易商出售材料就给高分。"
    "next_action围绕零件用途、材料牌号、规格/图纸、工况和采购需求给出核实建议，不得臆造需求。"
    "未知字段留空；不要假定本厂能供应所有关注材料或零件，替代材料及供货能力均需另行确认。"
)
DEFAULT_DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_lead_lock = asyncio.Lock()
_intel_lock = asyncio.Lock()
_chat_lock = asyncio.Lock()
_usage_lock = asyncio.Lock()
_analysis_lock = asyncio.Lock()
BATCH_FILE = AI_DIR / "analysis_batch.json"
_batch_task = None
_batch_stop = False
_linkedin_task = None
_linkedin_job = {"status": "idle"}
_similar_task = None
_similar_job = {"status": "idle"}
PLATFORM_DATA_DIRS = {"dy": "douyin", "wb": "weibo"}
CANADA_TIMEZONES = {"America/Toronto", "America/Winnipeg", "America/Edmonton", "America/Vancouver", "America/St_Johns"}


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
    max_leads: int = Field(default=50, ge=1, le=50)


class LeadUpdate(BaseModel):
    followed_up: bool | None = None
    low_relevance: bool | None = None
    manual_notes: str | None = Field(default=None, max_length=2000)
    recommended_email: str | None = Field(default=None, max_length=8000)
    recommended_email_subject: str | None = Field(default=None, max_length=300)


class EmailTranslationRequest(BaseModel):
    email: str = Field(min_length=1, max_length=8000)
    subject: str = Field(default="关于工程塑料型材及零部件合作咨询", min_length=1, max_length=300)
    language: Literal["英语", "韩语", "日语", "德语", "法语", "西班牙语"]


class EmailSendRequest(BaseModel):
    recipient: str = Field(min_length=3, max_length=320)
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=8000)


class EmailScheduleRequest(EmailSendRequest):
    scheduled_at: str = Field(min_length=16, max_length=40)
    timezone: str = Field(default="America/Toronto", max_length=64)


class LinkedInRequest(BaseModel):
    url: str = Field(min_length=1, max_length=500)


async def _linkedin_log(message: str, level: str = "info"):
    await crawler_manager._push_log(crawler_manager._create_log_entry(f"[LinkedIn] {message}", level))


async def _collect_linkedin(lead_id: str, name: str, url: str):
    try:
        await _linkedin_log(f"开始采集 {name}；仅处理此企业")
        await _linkedin_log(f"正在读取公司页面：{url}")
        company = await fetch_company(url)
        incoming = lead_fields(company, url)
        await _linkedin_log(f"读取完成：{company['name']}；正在合并到 {name}")
        async with _lead_lock:
            leads = _read_leads()
            target = next((item for item in leads if item.get("id") == lead_id), None)
            if target is None:
                raise ValueError("原企业已删除，取消合并")
            # Only update the chosen row; preserve its ID, name, follow-up and old sources.
            target.update(_merge_lead(target, incoming))
            _write_leads(leads)
        message = f"{name}：领英资料已合并，原始资料和跟进状态已保留（未调用 AI）"
        _linkedin_job.update(status="completed", message=message)
        await _linkedin_log(message, "success")
    except asyncio.CancelledError:
        _linkedin_job.update(status="error", message="领英任务已中止，未完成合并")
        raise
    except Exception as error:
        message = str(error) if isinstance(error, ValueError) else "领英处理失败，请稍后重试"
        _linkedin_job.update(status="error", message=message)
        await _linkedin_log(f"{name}：{message}", "error")


@router.get("/linkedin/status")
async def linkedin_status():
    return _linkedin_job


@router.post("/leads/{lead_id}/linkedin")
async def collect_linkedin(lead_id: str, request: LinkedInRequest):
    global _linkedin_task, _linkedin_job
    if _linkedin_task and not _linkedin_task.done():
        raise HTTPException(409, "已有一家企业正在读取领英，请等待完成")
    try:
        url = company_url(request.url)
    except ValueError as error:
        raise HTTPException(400, str(error)) from None
    lead = next((item for item in _read_leads() if item.get("id") == lead_id), None)
    if not lead:
        raise HTTPException(404, "企业不存在")
    _linkedin_job = {"id": uuid4().hex, "lead_id": lead_id, "status": "running",
                     "message": f"正在读取 {lead['company_name']} 的领英资料…"}
    _linkedin_task = asyncio.create_task(_collect_linkedin(lead_id, lead["company_name"], url))
    return _linkedin_job


async def _find_similar(lead_id: str, name: str):
    try:
        result = await chat(ChatRequest(
            message=(
                f"请以企业线索库中的‘{name}’为样本，先判断其企业角色、主营业务、产品、应用行业和客户类型，"
                "再强制联网搜索同类型企业。最多返回并保存20家可核验且不含样本企业的公司；不足20家时只返回有可靠公开证据的企业，禁止凑数。"
                "逐家判断使用PEEK或PEI材料/零件的可能性，potential_score填写该使用可能性的0-100评分，并在evidence中写明同类型依据、"
                "材料应用证据、判断理由和实际来源网页。优先终端零件用户、设备制造商和加工商，区分贸易商与材料供应商；"
                "核实企业全称、简称、国家地区、官网、联系方式、产品、专利和来源链接，未知字段留空。搜索结果按现有去重规则合并进企业线索库。"
            ),
            max_leads=20,
        ))
        _similar_job.update(status="completed", message=f"{name}：同类企业搜索完成", answer=result["answer"])
    except asyncio.CancelledError:
        _similar_job.update(status="error", message="同类企业任务已中止")
        raise
    except Exception as error:
        detail = error.detail if isinstance(error, HTTPException) else str(error)
        _similar_job.update(status="error", message=f"{name}：{detail}")


@router.get("/similar/status")
async def similar_status():
    return _similar_job


@router.post("/leads/{lead_id}/similar")
async def find_similar(lead_id: str):
    global _similar_task, _similar_job
    if _similar_task and not _similar_task.done():
        raise HTTPException(409, "已有一家企业正在搜索同类企业，请等待完成")
    if _batch_task and not _batch_task.done():
        raise HTTPException(409, "后台正在分批分析，请完成或停止后再搜索同类企业")
    if not _secret("DASHSCOPE_API_KEY", "dashscope_api_key"):
        raise HTTPException(503, "服务器尚未配置千问密钥")
    lead = next((item for item in _read_leads() if item.get("id") == lead_id), None)
    if not lead:
        raise HTTPException(404, "企业不存在")
    _similar_job = {"id": uuid4().hex, "lead_id": lead_id, "status": "running",
                    "message": f"正在查找与 {lead['company_name']} 同类型的企业…"}
    _similar_task = asyncio.create_task(_find_similar(lead_id, lead["company_name"]))
    return _similar_job


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
        elif key in {"company_info", "evidence", "next_action", "manual_notes"}:
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
            "low_relevance": leads[target_index].get("low_relevance", False),
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
                lead.update({"id": uuid4().hex, "followed_up": False, "low_relevance": False, "created_at": now, "updated_at": now})
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


def _recommended_email_prompt(lead: dict) -> str:
    fields = ("company_name", "aliases", "company_info", "country", "website", "contact_person", "email", "phone", "address", "keywords", "evidence", "next_action")
    context = {field: str(lead.get(field, "") or "") for field in fields}
    return (
        "仅根据以下企业资料，写一段70-130字的中文客户关联说明，用于插入商务开发邮件中间。"
        "只说明资料中明确、有证据的行业、产品或应用，以及其可能的材料或零部件需求；证据不足时使用谨慎表述，不得断言客户正在使用某一材料。"
        "不要写主题、称呼、问候、我方介绍、结尾、联系方式或网址；不要提及聚泰；避免‘高度关注’、‘深感契合’等空泛措辞，不得编造需求、案例、认证或价格。"
        "只返回这一段自然商务中文。\n\n企业资料：\n"
        + json.dumps(context, ensure_ascii=False)
    )


def _recommended_email_template(lead: dict, middle: str) -> str:
    contact = str(lead.get("contact_person", "") or "").strip()
    greeting = f"尊敬的{contact}：" if contact else "尊敬的负责人："
    return (
        "主题：关于高性能工程塑料型材及零部件合作\n\n"
        f"{greeting}\n您好！\n\n"
        "我是中国苏州聚泰新材料有限公司的业务代表。我们专注于PEEK、PEI、PSU等高性能工程塑料型材的研发、生产与销售，可提供标准及定制型材，以及精密机加工和注塑零部件服务。\n\n"
        f"{middle.strip()}\n\n"
        "如贵司有相关零部件需求，欢迎随时联系我们。我们愿意根据应用场景、性能要求及数量，提供合适的材料或零部件方案与报价。\n\n"
        "官网：https://www.jutaiplas.com/\n"
        "邮箱：inquiry@jutaipolymer.com"
    )


def _plain_email_text(value: str) -> str:
    return re.sub(r"\[([^\]]*)\]\((https?://[^)\s]+)\)", r"\2", value).strip()


def _email_parts(value: str, fallback_subject: str = "关于工程塑料型材及零部件合作咨询") -> tuple[str, str]:
    match = re.match(r"^\s*(?:主题|subject)\s*[:：]\s*(.+?)\s*(?:\r?\n){1,2}", value, re.IGNORECASE)
    return (match.group(1).strip(), value[match.end():].strip()) if match else (fallback_subject, value.strip())


def _translation_prompt(email: str, language: str) -> str:
    return f"将以下商务邮件完整翻译为{language}，使用该语言母语商务开发信的自然、简洁语气。保留主题、段落、公司名、数字和纯文本网址；不得补充未经证实的客户情况或营销承诺。英语必须使用‘Dear …’或‘Dear Sir or Madam,’开头，不要使用‘Hello!’或生硬直译；避免‘this has drawn our close attention’等表达。第一行保留‘Subject:’或对应语言的主题格式，空一行后为正文。不要增加解释、注释、Markdown或链接格式，只返回可直接发送的邮件文本。\n\n{email}"


async def _save_recommended_email(lead_id: str, email: str, translations: dict[str, str] | None = None, subject: str | None = None, translation_subjects: dict[str, str] | None = None) -> dict:
    async with _lead_lock:
        leads = _read_leads()
        lead = next((item for item in leads if item.get("id") == lead_id), None)
        if not lead:
            raise HTTPException(404, "企业不存在")
        lead["recommended_email"] = email.strip()
        if subject is not None:
            lead["recommended_email_subject"] = subject.strip()
        if translations is not None:
            lead["recommended_email_translations"] = translations
        if translation_subjects is not None:
            lead["recommended_email_translation_subjects"] = translation_subjects
        lead["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_leads(leads)
        return lead


async def _mark_recommended_email_sent(lead_id: str) -> dict:
    async with _lead_lock:
        leads = _read_leads()
        lead = next((item for item in leads if item.get("id") == lead_id), None)
        if not lead:
            raise HTTPException(404, "企业不存在")
        now = datetime.now(timezone.utc).isoformat()
        lead["recommended_email_sent_at"] = now
        lead["updated_at"] = now
        _write_leads(leads)
        return lead


def _scheduled_at(value: str, timezone_name: str) -> datetime:
    if timezone_name not in CANADA_TIMEZONES:
        raise HTTPException(422, "请选择加拿大时区")
    try:
        local = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(422, "定时发送时间无效") from None
    if local.tzinfo is not None:
        raise HTTPException(422, "定时发送时间无效")
    due = local.replace(tzinfo=ZoneInfo(timezone_name)).astimezone(timezone.utc)
    if due <= datetime.now(timezone.utc):
        raise HTTPException(422, "定时发送时间必须在未来")
    return due


def _recipient_address(value: str) -> str:
    if "\r" in value or "\n" in value:
        raise HTTPException(422, "收件人地址无效")
    address = parseaddr(value)[1]
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", address):
        raise HTTPException(422, "收件人地址无效")
    return address


def _append_bossmail_sent(message: EmailMessage, sender: str, password: str) -> str:
    host = os.getenv("BOSSMAIL_IMAP_HOST", "p212r.chinaemail.cn").strip()
    try:
        port = int(os.getenv("BOSSMAIL_IMAP_PORT", "993"))
    except ValueError:
        return "已投递，但已发邮件副本保存失败"
    try:
        with imaplib.IMAP4_SSL(host, port, timeout=30) as client:
            client.login(sender, password)
            status, _ = client.append("INBOX.Sent", "\\Seen", None, message.as_bytes())
            if status != "OK":
                return "已投递，但已发邮件副本保存失败"
    except (OSError, imaplib.IMAP4.error):
        return "已投递，但已发邮件副本保存失败"
    return ""


def _send_bossmail(recipient: str, subject: str, body: str) -> str:
    host = os.getenv("BOSSMAIL_SMTP_HOST", "").strip()
    password = os.getenv("BOSSMAIL_SMTP_PASSWORD", "").strip()
    sender = os.getenv("BOSSMAIL_SMTP_USERNAME", "inquiry@jutaipolymer.com").strip()
    try:
        port = int(os.getenv("BOSSMAIL_SMTP_PORT", "465"))
    except ValueError:
        raise RuntimeError("SMTP端口配置无效")
    if not host or not password or not sender:
        raise RuntimeError("SMTP尚未配置")
    message = EmailMessage()
    message["From"] = f"中国苏州聚泰新材料有限公司 <{sender}>"
    message["To"] = recipient
    message["Subject"] = subject.replace("\r", "").replace("\n", "").strip()
    message.set_content(body)
    with smtplib.SMTP_SSL(host, port, timeout=30, context=ssl.create_default_context()) as client:
        client.login(sender, password)
        client.send_message(message)
    return _append_bossmail_sent(message, sender, password)


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
        "material_scope": MATERIAL_SCOPE,
        "api_configured": bool(_secret("DASHSCOPE_API_KEY", "dashscope_api_key")),
        "access_configured": True,
        "usage": _read_usage(),
    }


@router.post("/leads/{lead_id}/recommended-email")
async def recommended_email(lead_id: str):
    if _batch_task and not _batch_task.done():
        raise HTTPException(409, "后台正在分批分析，请完成或停止后再生成推荐邮件")
    api_key = _secret("DASHSCOPE_API_KEY", "dashscope_api_key")
    if not api_key:
        raise HTTPException(503, "服务器尚未配置千问密钥")
    lead = next((item for item in _read_leads() if item.get("id") == lead_id), None)
    if not lead:
        raise HTTPException(404, "企业不存在")
    async with httpx.AsyncClient(trust_env=False, timeout=60.0) as client:
        response = await client.post(
            f"{_dashscope_base_url()}/chat/completions",
            json={"model": MODEL, "messages": [{"role": "user", "content": _recommended_email_prompt(lead)}], "enable_thinking": False, "max_completion_tokens": 1000},
            headers={"Authorization": f"Bearer {api_key}"},
        )
    if not response.is_success:
        try:
            detail = response.json().get("error", {}).get("message", response.reason_phrase)
        except ValueError:
            detail = response.reason_phrase
        raise HTTPException(502, detail=f"千问 API error: {detail}")
    body = response.json()
    await _record_usage(body.get("usage", {}))
    middle = _plain_email_text(_response_text(body))
    middle = re.sub(r"^\s*(?:主题|subject)\s*[:：].*(?:\r?\n)+", "", middle, flags=re.IGNORECASE).strip()
    if not middle:
        raise HTTPException(502, "千问未返回客户关联说明")
    subject, email = _email_parts(_recommended_email_template(lead, middle))
    lead = await _save_recommended_email(lead_id, email, {}, subject, {})
    return {"email": email, "subject": subject, "lead": lead}


@router.post("/leads/{lead_id}/translate-email")
async def translate_recommended_email(lead_id: str, request: EmailTranslationRequest):
    if _batch_task and not _batch_task.done():
        raise HTTPException(409, "后台正在分批分析，请完成或停止后再翻译")
    api_key = _secret("DASHSCOPE_API_KEY", "dashscope_api_key")
    if not api_key:
        raise HTTPException(503, "服务器尚未配置千问密钥")
    lead = next((item for item in _read_leads() if item.get("id") == lead_id), None)
    if not lead:
        raise HTTPException(404, "企业不存在")
    source = request.email.strip()
    subject = request.subject.strip()
    source_matches_lead = source == str(lead.get("recommended_email", "")).strip() and subject == str(lead.get("recommended_email_subject", "关于工程塑料型材及零部件合作咨询")).strip()
    existing = lead.get("recommended_email_translations", {})
    existing_subjects = lead.get("recommended_email_translation_subjects", {})
    translations = dict(existing) if source_matches_lead and isinstance(existing, dict) else {}
    translation_subjects = dict(existing_subjects) if source_matches_lead and isinstance(existing_subjects, dict) else {}
    async with httpx.AsyncClient(trust_env=False, timeout=60.0) as client:
        response = await client.post(
            f"{_dashscope_base_url()}/chat/completions",
            json={"model": MODEL, "messages": [{"role": "user", "content": _translation_prompt(f"主题：{subject}\n\n{source}", request.language)}], "enable_thinking": False, "max_completion_tokens": 1600},
            headers={"Authorization": f"Bearer {api_key}"},
        )
    if not response.is_success:
        try:
            detail = response.json().get("error", {}).get("message", response.reason_phrase)
        except ValueError:
            detail = response.reason_phrase
        raise HTTPException(502, detail=f"千问 API error: {detail}")
    body = response.json()
    await _record_usage(body.get("usage", {}))
    translation = _plain_email_text(_response_text(body))
    if not translation:
        raise HTTPException(502, "千问未返回译文")
    translation_subject, translation_body = _email_parts(translation, subject)
    translations[request.language] = translation_body
    translation_subjects[request.language] = translation_subject
    lead = await _save_recommended_email(lead_id, source, translations, subject, translation_subjects)
    return {"translation": translation_body, "subject": translation_subject, "lead": lead}


async def run_scheduled_mail_once():
    due_jobs = []
    now = datetime.now(timezone.utc)
    async with _lead_lock:
        leads = _read_leads()
        changed = False
        for lead in leads:
            job = lead.get("scheduled_email")
            if not isinstance(job, dict) or job.get("status") != "scheduled":
                continue
            try:
                due = datetime.fromisoformat(str(job.get("due_at", "")))
            except ValueError:
                job.update(status="failed", error="定时发送时间无效")
                changed = True
                continue
            if due.tzinfo and due <= now:
                job["status"] = "sending"
                due_jobs.append((lead["id"], dict(job)))
                changed = True
        if changed:
            _write_leads(leads)
    for lead_id, job in due_jobs:
        try:
            await asyncio.to_thread(_send_bossmail, job["recipient"], job["subject"], job["body"])
        except (OSError, smtplib.SMTPException, RuntimeError) as error:
            status, error_text = "failed", str(error)
            await crawler_manager._push_log(crawler_manager._create_log_entry(f"[Mail] 定时发送给 {job['recipient']} 失败：{error}", "error"))
        else:
            status, error_text = "sent", ""
            await crawler_manager._push_log(crawler_manager._create_log_entry(f"[Mail] 已定时发送推荐邮件至 {job['recipient']}", "success"))
        async with _lead_lock:
            leads = _read_leads()
            lead = next((item for item in leads if item.get("id") == lead_id), None)
            if lead and isinstance(lead.get("scheduled_email"), dict):
                sent_at = datetime.now(timezone.utc).isoformat()
                lead["scheduled_email"].update(status=status, sent_at=sent_at, error=error_text)
                if status == "sent":
                    lead["recommended_email_sent_at"] = sent_at
                lead["updated_at"] = sent_at
                _write_leads(leads)


@router.post("/leads/{lead_id}/schedule-email")
async def schedule_recommended_email(lead_id: str, request: EmailScheduleRequest):
    recipient = _recipient_address(request.recipient)
    if "\r" in request.subject or "\n" in request.subject:
        raise HTTPException(422, "邮件主题无效")
    due = _scheduled_at(request.scheduled_at, request.timezone)
    async with _lead_lock:
        leads = _read_leads()
        lead = next((item for item in leads if item.get("id") == lead_id), None)
        if not lead:
            raise HTTPException(404, "企业不存在")
        lead["scheduled_email"] = {"recipient": recipient, "subject": request.subject.strip(), "body": request.body.strip(), "due_at": due.isoformat(), "local_time": request.scheduled_at, "timezone": request.timezone, "status": "scheduled"}
        lead["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_leads(leads)
        return {"lead": lead}


@router.post("/leads/{lead_id}/send-email")
async def send_recommended_email(lead_id: str, request: EmailSendRequest):
    if not next((item for item in _read_leads() if item.get("id") == lead_id), None):
        raise HTTPException(404, "企业不存在")
    recipient = _recipient_address(request.recipient)
    if "\r" in request.subject or "\n" in request.subject:
        raise HTTPException(422, "邮件主题无效")
    try:
        sent_copy_warning = await asyncio.to_thread(_send_bossmail, recipient, request.subject, request.body)
    except (OSError, smtplib.SMTPException, RuntimeError) as error:
        await crawler_manager._push_log(crawler_manager._create_log_entry(f"[Mail] 发送给 {recipient} 失败：{error}", "error"))
        raise HTTPException(502, "邮件发送失败，请核对 SMTP 配置和收件人地址") from error
    lead = await _mark_recommended_email_sent(lead_id)
    detail = f"[Mail] 已发送推荐邮件至 {recipient}" + (f"；{sent_copy_warning}" if sent_copy_warning else "")
    await crawler_manager._push_log(crawler_manager._create_log_entry(detail, "warning" if sent_copy_warning else "success"))
    return {"sent": True, "recipient": recipient, "sent_at": lead["recommended_email_sent_at"], "lead": lead, "warning": sent_copy_warning}


@router.post("/chat")
async def chat(request: ChatRequest):
    if _batch_task and not _batch_task.done() and asyncio.current_task() is not _batch_task:
        raise HTTPException(status_code=409, detail="后台正在分批分析，请完成或停止后再发送")
    if _similar_task and not _similar_task.done() and asyncio.current_task() is not _similar_task:
        raise HTTPException(status_code=409, detail="后台正在搜索同类企业，请等待完成")
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
            "你是B2B潜客与行业情报分析助手。" + CUSTOMER_FOCUS +
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

    leads = _normalize_leads([lead for result in results for lead in result.get("leads", [])])[:request.max_leads]
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
                message=f"第 {job['batches'] + 1} 批：分析以下全部记录，按系统定义的完整材料范围识别高性能工程塑料零件用户及行业情报，区分企业角色、材料牌号、零件用途、事实和推测，标明来源、日期、可靠度。",
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
        if _similar_task and not _similar_task.done():
            raise HTTPException(status_code=409, detail="后台正在搜索同类企业，请等待完成")
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
    return {"leads": _read_leads()}


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
    changes = request.model_dump(exclude_unset=True)
    if not changes or any(changes.get(key) is None for key in ("followed_up", "low_relevance") if key in changes):
        raise HTTPException(status_code=400, detail="没有可保存的线索修改")
    if "manual_notes" in changes:
        changes["manual_notes"] = (changes["manual_notes"] or "").strip()
    if "recommended_email" in changes:
        changes["recommended_email"] = (changes["recommended_email"] or "").strip()
    if "recommended_email_subject" in changes:
        changes["recommended_email_subject"] = (changes["recommended_email_subject"] or "").strip()
    async with _lead_lock:
        leads = _read_leads()
        for lead in leads:
            if lead.get("id") == lead_id:
                if ("recommended_email" in changes or "recommended_email_subject" in changes) and (changes.get("recommended_email", lead.get("recommended_email", "")) != lead.get("recommended_email", "") or changes.get("recommended_email_subject", lead.get("recommended_email_subject", "")) != lead.get("recommended_email_subject", "")):
                    changes["recommended_email_translations"] = {}
                    changes["recommended_email_translation_subjects"] = {}
                lead.update(changes)
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
        "evidence", "potential_score", "next_action", "manual_notes", "followed_up", "low_relevance", "created_at", "updated_at",
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
