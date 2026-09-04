"""Isolated LinkedIn company reader: no AI-generated URLs or credentials in logs."""
import asyncio
import json
import os
import re
import signal
from pathlib import Path
from urllib.parse import urlsplit


def company_url(value: str) -> str:
    url = urlsplit(value.strip())
    if (url.scheme != "https" or url.hostname not in {"linkedin.com", "www.linkedin.com"}
            or url.username or url.password or url.port
            or not re.fullmatch(r"/company/[A-Za-z0-9_-]+/?(?:about/?)?", url.path)):
        raise ValueError("请输入有效的领英公司链接：https://www.linkedin.com/company/公司标识/")
    return f"https://www.linkedin.com/company/{url.path.split('/')[2]}/"


def lead_fields(company: dict, url: str) -> dict:
    name = str(company.get("name") or "").strip()
    if not name or name.casefold() == "unknown company":
        raise ValueError("未读取到有效公司名称，未合并任何资料")
    info = [f"领英公司名称：{name}"]
    for field, label in [("about_us", "简介"), ("industry", "行业"), ("company_size", "规模"),
                         ("company_type", "类型"), ("founded", "成立年份"), ("specialties", "专长")]:
        if company.get(field):
            info.append(f"{label}：{company[field]}")
    website = str(company.get("website") or "").strip()
    if website and not website.startswith(("https://", "http://")):
        website = ""
    return {"aliases": name, "company_info": "\n".join(info), "website": website,
            "phone": str(company.get("phone") or ""), "address": str(company.get("headquarters") or ""),
            "source_platform": "LinkedIn", "source_urls": url,
            "evidence": f"领英公司页面公开自述（未独立核验，不代表采购需求）：{url}"}


async def fetch_company(url: str) -> dict:
    executable = Path(os.getenv("LINKEDIN_PYTHON", str(Path.home() / "linkedin_scraper/.venv/bin/python")))
    if not executable.is_file():
        raise ValueError("领英运行环境未安装")
    process = await asyncio.create_subprocess_exec(
        str(executable), str(Path(__file__).resolve()), company_url(url),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, start_new_session=True,
    )
    try:
        try:
            output, _ = await asyncio.wait_for(process.communicate(), timeout=120)
        except asyncio.TimeoutError:
            raise ValueError("领英读取超时，已终止本次浏览器；请稍后重试") from None
        try:
            result = json.loads(output)
        except (ValueError, UnicodeError):
            raise ValueError("领英进程未返回有效数据，未合并资料") from None
        if process.returncode or result.get("error"):
            raise ValueError(result.get("error", "领英采集失败"))
        return result
    finally:
        # Kill the isolated group even if its parent exited, so browsers cannot linger.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()


async def _read(url):
    from linkedin_scraper import BrowserManager, CompanyScraper
    from linkedin_scraper.core.auth import is_logged_in
    session = Path.home() / ".local/share/linkedin-scraper/session.json"
    if not session.exists():
        raise ValueError("领英尚未登录，请先在服务器浏览器完成登录")
    async with BrowserManager(headless=True, proxy={"server": os.getenv("INTERNATIONAL_PROXY", "http://127.0.0.1:7890")}) as browser:
        await browser.load_session(str(session))
        await browser.page.goto(url, wait_until="domcontentloaded")
        if not await is_logged_in(browser.page):
            raise ValueError("领英登录已失效或需要人工验证，请重新登录；未合并资料")
        result = await CompanyScraper(browser.page).scrape(url)
        value = result.model_dump(mode="json")
        lead_fields(value, url)
        return value


if __name__ == "__main__":
    import sys
    try:
        print(json.dumps(asyncio.run(_read(company_url(sys.argv[1]))), ensure_ascii=False))
    except Exception as error:
        # Never expose library exceptions which may contain browser state or credentials.
        message = str(error) if isinstance(error, ValueError) else "领英采集失败（网络、访问限制或页面变化），请检查登录状态后重试"
        print(json.dumps({"error": message}, ensure_ascii=False))
        sys.exit(1)
