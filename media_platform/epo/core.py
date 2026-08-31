import asyncio
import os
import xml.etree.ElementTree as ET
from typing import Any

import httpx

import config
from base.base_crawler import AbstractCrawler
from tools.async_file_writer import AsyncFileWriter
from var import crawler_type_var, source_keyword_var


TOKEN_URL = "https://ops.epo.org/3.2/auth/accesstoken"
SEARCH_URL = "https://ops.epo.org/3.2/rest-services/published-data/search/biblio"
PROXY = os.getenv("INTERNATIONAL_PROXY", "http://127.0.0.1:7890")
REQUEST_INTERVAL = float(os.getenv("EPO_OPS_REQUEST_INTERVAL", "6.2"))


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(element: ET.Element, name: str):
    return (child for child in element.iter() if _local_name(child.tag) == name)


def _text(element: ET.Element | None) -> str:
    return " ".join("".join(element.itertext()).split()) if element is not None else ""


def _unique(values):
    return list(dict.fromkeys(value for value in values if value))


class EPOCrawler(AbstractCrawler):
    platform = "epo"

    def __init__(self):
        self.key = (os.getenv("EPO_OPS_CONSUMER_KEY") or os.getenv("EPO_OPS_KEY") or "").strip()
        self.secret = (os.getenv("EPO_OPS_CONSUMER_SECRET") or os.getenv("EPO_OPS_SECRET") or "").strip()
        self.client: httpx.AsyncClient | None = None
        self.token = ""

    async def start(self):
        if not self.key or not self.secret:
            raise ValueError(
                "EPO OPS credentials are missing: set EPO_OPS_CONSUMER_KEY and "
                "EPO_OPS_CONSUMER_SECRET on the server"
            )
        if config.CRAWLER_TYPE != "search":
            raise ValueError("EPO OPS currently supports keyword search only")
        if config.SAVE_DATA_OPTION not in {"json", "jsonl", "csv"}:
            raise ValueError("EPO OPS currently supports JSON, JSONL and CSV storage only")
        if config.CRAWLER_MAX_NOTES_COUNT > 500:
            raise ValueError("EPO OPS supports at most 500 patents per keyword in this UI")

        crawler_type_var.set(config.CRAWLER_TYPE)
        self.client = httpx.AsyncClient(
            proxy=PROXY,
            timeout=httpx.Timeout(45.0),
            trust_env=False,
            headers={"Accept": "application/exchange+xml"},
        )
        try:
            await self._authenticate()
            await self.search()
        finally:
            await self.client.aclose()
            self.client = None

    async def _authenticate(self):
        assert self.client is not None
        response = await self.client.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=httpx.BasicAuth(self.key, self.secret),
            headers={"Accept": "application/json"},
        )
        if not response.is_success:
            raise RuntimeError(
                f"EPO OPS authentication failed (HTTP {response.status_code}); "
                "check the Consumer Key and Consumer Secret"
            )
        self.token = response.json().get("access_token", "")
        if not self.token:
            raise RuntimeError("EPO OPS authentication returned no access token")

    async def search(self):
        writer = AsyncFileWriter(platform=self.platform, crawler_type="search")
        for keyword in filter(None, map(str.strip, config.KEYWORDS.split(","))):
            source_keyword_var.set(keyword)
            saved = 0
            begin = 1
            total = None
            while saved < config.CRAWLER_MAX_NOTES_COUNT:
                end = begin + min(100, config.CRAWLER_MAX_NOTES_COUNT - saved) - 1
                if begin > 1:
                    await asyncio.sleep(REQUEST_INTERVAL)
                root = await self._search_page(keyword, begin, end)
                total = self._total_results(root)
                patents = self._parse_patents(root, keyword)
                if not patents:
                    break
                for patent in patents:
                    await self._write(writer, patent)
                    saved += 1
                    print(
                        f"[epo] {keyword}: saved {saved}/{min(total or saved, config.CRAWLER_MAX_NOTES_COUNT)} patents; "
                        f"applicants: {patent['applicants'] or '-'}"
                    )
                    if saved >= config.CRAWLER_MAX_NOTES_COUNT:
                        break
                begin = end + 1
                if total is not None and begin > total:
                    break
            print(f"[epo] {keyword}: completed; saved {saved} patents; OPS matched {total or 0}")

    async def _search_page(self, keyword: str, begin: int, end: int) -> ET.Element:
        assert self.client is not None
        response = await self.client.get(
            SEARCH_URL,
            params={"q": self._cql(keyword)},
            headers={
                "Authorization": f"Bearer {self.token}",
                "X-OPS-Range": f"{begin}-{end}",
            },
        )
        throttle = response.headers.get("X-Throttling-Control")
        if throttle:
            print(f"[epo] OPS throttling status: {throttle}")
        if response.status_code == 401:
            raise RuntimeError("EPO OPS rejected the access token; check the configured credentials")
        if response.status_code == 429:
            raise RuntimeError("EPO OPS rate limit reached; wait before searching again")
        if not response.is_success:
            detail = _text(ET.fromstring(response.content)) if response.content.startswith(b"<") else response.text
            raise RuntimeError(f"EPO OPS search failed (HTTP {response.status_code}): {detail[:300]}")
        return ET.fromstring(response.content)

    @staticmethod
    def _cql(keyword: str) -> str:
        escaped = keyword.replace("\\", "\\\\").replace('"', '\\"')
        return f'ta all "{escaped}"'

    @staticmethod
    def _total_results(root: ET.Element) -> int | None:
        search = next(_children(root, "biblio-search"), None)
        value = search.get("total-result-count") if search is not None else None
        return int(value) if value and value.isdigit() else None

    @classmethod
    def _parse_patents(cls, root: ET.Element, keyword: str) -> list[dict[str, Any]]:
        return [cls._patent_item(document, keyword) for document in _children(root, "exchange-document")]

    @staticmethod
    def _patent_item(document: ET.Element, keyword: str) -> dict[str, Any]:
        country = document.get("country", "")
        doc_number = document.get("doc-number", "")
        kind = document.get("kind", "")
        publication_number = f"{country}{doc_number}{kind}"

        titles = list(_children(document, "invention-title"))
        title_node = next((item for item in titles if item.get("lang") == "en"), titles[0] if titles else None)
        abstracts = list(_children(document, "abstract"))
        abstract_node = next((item for item in abstracts if item.get("lang") == "en"), abstracts[0] if abstracts else None)

        applicants = _unique(
            _text(name)
            for applicant in _children(document, "applicant")
            for applicant_name in _children(applicant, "applicant-name")
            for name in _children(applicant_name, "name")
        )
        applicant_countries = _unique(
            _text(country_node)
            for applicant in _children(document, "applicant")
            for country_node in _children(applicant, "country")
        )
        applicant_addresses = _unique(
            _text(address)
            for applicant in _children(document, "applicant")
            for address in _children(applicant, "address")
        )
        inventors = _unique(
            _text(name)
            for inventor in _children(document, "inventor")
            for inventor_name in _children(inventor, "inventor-name")
            for name in _children(inventor_name, "name")
        )

        publication_date = EPOCrawler._reference_value(document, "publication-reference", "date")
        application_number = EPOCrawler._reference_value(document, "application-reference", "doc-number")
        filing_date = EPOCrawler._reference_value(document, "application-reference", "date")
        priority_dates = [
            _text(date)
            for claim in _children(document, "priority-claim")
            for date in _children(claim, "date")
        ]
        classifications = _unique(
            _text(text)
            for classification in _children(document, "classification-ipcr")
            for text in _children(classification, "text")
        )

        return {
            "platform": "epo",
            "keyword": keyword,
            "publication_number": publication_number,
            "country": country,
            "doc_number": doc_number,
            "kind": kind,
            "title": _text(title_node),
            "abstract": _text(abstract_node),
            "applicants": "; ".join(applicants),
            "applicant_countries": "; ".join(applicant_countries),
            "applicant_addresses": "; ".join(applicant_addresses),
            "inventors": "; ".join(inventors),
            "publication_date": publication_date,
            "application_number": application_number,
            "filing_date": filing_date,
            "priority_date": min(priority_dates) if priority_dates else "",
            "classifications": "; ".join(classifications),
            "family_id": document.get("family-id", ""),
            "potential_customers": "; ".join(applicants),
            "lead_reason": f"Applicant on a patent whose title or abstract matches: {keyword}",
            "url": f"https://worldwide.espacenet.com/patent/search?q=pn%3D{publication_number}",
        }

    @staticmethod
    def _reference_value(document: ET.Element, reference_name: str, field_name: str) -> str:
        reference = next(_children(document, reference_name), None)
        if reference is None:
            return ""
        doc_ids = list(_children(reference, "document-id"))
        doc_id = next((item for item in doc_ids if item.get("document-id-type") == "docdb"), doc_ids[0] if doc_ids else None)
        return _text(next(_children(doc_id, field_name), None)) if doc_id is not None else ""

    async def _write(self, writer: AsyncFileWriter, item: dict[str, Any]):
        if config.SAVE_DATA_OPTION == "csv":
            await writer.write_to_csv(item, "contents")
        elif config.SAVE_DATA_OPTION == "jsonl":
            await writer.write_to_jsonl(item, "contents")
        else:
            await writer.write_single_item_to_json(item, "contents")

    async def launch_browser(self, *args, **kwargs):
        raise NotImplementedError
