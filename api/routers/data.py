# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/api/routers/data.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#
# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。

import os
import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/data", tags=["data"])

# Data directory
DATA_DIR = Path(__file__).parent.parent.parent / "data"
AI_DIR = DATA_DIR / "ai"
SUPPORTED_EXTENSIONS = {".json", ".csv", ".xlsx", ".xls"}


class RenameFileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


def resolve_managed_file(file_path: str) -> Path:
    """Resolve a browser-managed data file without allowing path traversal."""
    full_path = (DATA_DIR / file_path).resolve()
    try:
        full_path.relative_to(DATA_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")
    if full_path == AI_DIR.resolve() or AI_DIR.resolve() in full_path.parents:
        raise HTTPException(status_code=403, detail="AI lead files are managed by the lead workspace")
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if not full_path.is_file() or full_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Not a managed data file")
    return full_path


def iter_data_files():
    """Yield only files managed by the data browser."""
    if not DATA_DIR.exists():
        return

    for root, _, filenames in os.walk(DATA_DIR):
        root_path = Path(root)
        if root_path == AI_DIR or AI_DIR in root_path.parents:
            continue
        for filename in filenames:
            file_path = root_path / filename
            if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
                yield file_path


def get_file_info(file_path: Path) -> dict:
    """Get file information"""
    stat = file_path.stat()
    record_count = None

    # Try to get record count
    try:
        if file_path.suffix == ".json":
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    record_count = len(data)
        elif file_path.suffix == ".csv":
            with open(file_path, "r", encoding="utf-8") as f:
                record_count = sum(1 for _ in f) - 1  # Subtract header row
    except Exception:
        pass

    return {
        "name": file_path.name,
        "path": str(file_path.relative_to(DATA_DIR)),
        "size": stat.st_size,
        "modified_at": stat.st_mtime,
        "record_count": record_count,
        "type": file_path.suffix[1:] if file_path.suffix else "unknown"
    }


@router.get("/files")
async def list_data_files(platform: Optional[str] = None, file_type: Optional[str] = None):
    """Get data file list"""
    if not DATA_DIR.exists():
        return {"files": []}

    files = []
    for file_path in iter_data_files():
        # Platform filter
        if platform:
            rel_path = str(file_path.relative_to(DATA_DIR))
            if platform.lower() not in rel_path.lower():
                continue

        # Type filter
        if file_type and file_path.suffix[1:].lower() != file_type.lower():
            continue

        try:
            files.append(get_file_info(file_path))
        except Exception:
            continue

    # Sort by modification time (newest first)
    files.sort(key=lambda x: x["modified_at"], reverse=True)

    return {"files": files}


@router.delete("/files")
async def delete_all_data_files():
    """Delete every file currently managed by the data browser."""
    deleted = 0
    failures = []

    for file_path in list(iter_data_files()):
        try:
            file_path.unlink()
            deleted += 1
        except OSError as exc:
            failures.append(f"{file_path.relative_to(DATA_DIR)}: {exc}")

    if failures:
        raise HTTPException(
            status_code=500,
            detail=f"Deleted {deleted} files, but failed to delete: {'; '.join(failures)}",
        )

    return {"deleted": deleted}


@router.delete("/files/{file_path:path}")
async def delete_data_file(file_path: str):
    """Delete one data file."""
    full_path = resolve_managed_file(file_path)
    try:
        full_path.unlink()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"deleted": file_path}


@router.patch("/files/{file_path:path}")
async def rename_data_file(file_path: str, request: RenameFileRequest):
    """Rename one data file in place, preserving its extension."""
    full_path = resolve_managed_file(file_path)
    name = request.name.strip()
    if not name or Path(name).name != name or name.startswith("."):
        raise HTTPException(status_code=400, detail="Use a plain file name")

    suffix = full_path.suffix.lower()
    if not Path(name).suffix:
        name += suffix
    elif Path(name).suffix.lower() != suffix:
        raise HTTPException(status_code=400, detail=f"File extension must remain {suffix}")

    target = full_path.with_name(name)
    if target.exists() and target != full_path:
        raise HTTPException(status_code=409, detail="A file with that name already exists")
    try:
        full_path.rename(target)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"file": get_file_info(target)}


@router.get("/files/{file_path:path}")
async def get_file_content(
    file_path: str,
    preview: bool = True,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    query: str = "",
):
    """Get file content or preview"""
    full_path = resolve_managed_file(file_path)

    if preview:
        # Return one page; search still scans the complete file.
        try:
            suffix = full_path.suffix.lower()
            if suffix == ".json":
                with open(full_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    rows = loaded if isinstance(loaded, list) else [loaded]
                columns = None
            elif suffix == ".csv":
                import csv
                with open(full_path, "r", encoding="utf-8") as f:
                    rows = list(csv.DictReader(f))
                columns = None
            elif suffix in (".xlsx", ".xls"):
                import pandas as pd
                df = pd.read_excel(full_path)
                rows = df.where(pd.notnull(df), None).to_dict(orient='records')
                columns = list(df.columns)
            else:
                raise HTTPException(status_code=400, detail="Unsupported file type for preview")

            all_total = len(rows)
            term = query.strip().casefold()
            if term:
                # ponytail: scan on demand; add an index only if large-file search becomes slow.
                rows = [
                    row for row in rows
                    if term in json.dumps(row, ensure_ascii=False, default=str).casefold()
                ]
            return {
                "data": rows[offset:offset + limit],
                "total": len(rows),
                "all_total": all_total,
                "columns": columns,
            }
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON file")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    else:
        # Return file download
        return FileResponse(
            path=full_path,
            filename=full_path.name,
            media_type="application/octet-stream"
        )


@router.get("/download/{file_path:path}")
async def download_file(file_path: str):
    """Download file"""
    full_path = resolve_managed_file(file_path)

    return FileResponse(
        path=full_path,
        filename=full_path.name,
        media_type="application/octet-stream"
    )


@router.get("/stats")
async def get_data_stats():
    """Get data statistics"""
    if not DATA_DIR.exists():
        return {"total_files": 0, "total_size": 0, "by_platform": {}, "by_type": {}}

    stats = {
        "total_files": 0,
        "total_size": 0,
        "by_platform": {},
        "by_type": {}
    }

    for file_path in iter_data_files():
        try:
            stat = file_path.stat()
            stats["total_files"] += 1
            stats["total_size"] += stat.st_size

            # Statistics by type
            file_type = file_path.suffix[1:].lower()
            stats["by_type"][file_type] = stats["by_type"].get(file_type, 0) + 1

            # Statistics by platform (inferred from path)
            rel_path = str(file_path.relative_to(DATA_DIR))
            for platform in ["xhs", "dy", "ks", "bili", "wb", "tieba", "zhihu", "youtube", "x"]:
                if platform in rel_path.lower():
                    stats["by_platform"][platform] = stats["by_platform"].get(platform, 0) + 1
                    break
        except Exception:
            continue

    return stats
