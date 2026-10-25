"""MCP server exposing Korea's DART disclosure system to English-speaking agents.

Every response keeps the original Korean next to an English rendering so the
calling model can translate further while still citing the source text.
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import logging
import os
import re
import sys
from collections import Counter, OrderedDict
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from typing import Any, Literal, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from . import analysis, glossary
from .client import DartClient, DartError
from .corp_codes import Corp, CorpIndex, load_corp_index
from .document import SECTION_ALIASES, FilingDocument, extract_section, find_snippets, parse_document_zip

log = logging.getLogger("dart_mcp")

VIEWER_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={}"
MAX_DOC_CHARS = 50_000

mcp = MCPServer(
    "dart",
    instructions=(
        "Tools for Korea's DART (Data Analysis, Retrieval and Transfer System), the FSS "
        "electronic disclosure system — the Korean equivalent of SEC EDGAR. Most filings "
        "exist only in Korean. Identify companies by 6-digit KRX ticker (e.g. 005930 = "
        "Samsung Electronics), DART corp_code, or name in English or Korean. Responses "
        "include original Korean (`*_ko`) with English renderings (`*_en`); when an `_en` "
        "field is null, translate the Korean yourself. Amounts are in KRW (won) unless a "
        "`currency` field says otherwise. Always cite `url` links to the original filing. "
        "Start with get_material_events for 'what's going on' questions, and read the "
        "dart://guide/korea-primer resource for market context."
    ),
)


# --- Service state ----------------------------------------------------------


class Service:
    def __init__(self) -> None:
        self._client: DartClient | None = None
        self._index: CorpIndex | None = None
        self._lock = asyncio.Lock()
        self._docs: OrderedDict[str, FilingDocument] = OrderedDict()

    @property
    def client(self) -> DartClient:
        if self._client is None:
            self._client = DartClient()
        return self._client

    async def index(self) -> CorpIndex:
        if self._index is None:
            async with self._lock:
                if self._index is None:
                    self._index = await load_corp_index(self.client)
                    log.info("Loaded %d DART companies", len(self._index))
        return self._index

    async def resolve(self, company: str) -> Corp:
        return (await self.index()).resolve(company)

    async def document(self, rcept_no: str) -> FilingDocument:
        if rcept_no in self._docs:
            self._docs.move_to_end(rcept_no)
            return self._docs[rcept_no]
        blob = await self.client.get_zip("document.xml", rcept_no=rcept_no)
        doc = await asyncio.to_thread(parse_document_zip, rcept_no, blob)
        self._docs[rcept_no] = doc
        if len(self._docs) > 20:
            self._docs.popitem(last=False)
        return doc


service = Service()

# All DART tools only read public data, so clients can safely auto-approve them.
READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True)

T = TypeVar("T")


def tool_errors(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
    """Turn expected failures into clear ToolErrors the agent can act on."""

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> T:
        try:
            return await fn(*args, **kwargs)
        except ToolError:
            raise
        except (LookupError, ValueError, DartError) as exc:
            raise ToolError(str(exc)) from exc
        except RuntimeError as exc:
            log.exception("Tool %s failed", fn.__name__)
            raise ToolError(str(exc)) from exc

    return wrapper


# --- Helpers ----------------------------------------------------------------


def parse_amount(value: str | None) -> int | float | None:
    if value is None:
        return None
    s = str(value).strip().replace(",", "")
    if s in ("", "-"):
        return None
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        num: int | float = int(s)
    except ValueError:
        try:
            num = float(s)
        except ValueError:
            return None
    return -num if negative else num


def parse_date(value: str | None, name: str) -> str | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    try:
        datetime.strptime(digits, "%Y%m%d")
    except ValueError:
        raise ValueError(f"{name} must be a date like 2024-03-31, got {value!r}") from None
    return digits


def fmt_date(yyyymmdd: str | None) -> str | None:
    if yyyymmdd and len(yyyymmdd) == 8 and yyyymmdd.isdigit():
        return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"
    return yyyymmdd or None


def report_code(period: str) -> str:
    try:
        return glossary.REPORT_CODES[period]
    except KeyError:
        raise ValueError(f"period must be one of {sorted(glossary.REPORT_CODES)}") from None


def check_year(year: int) -> str:
    if not 2015 <= year <= date.today().year:
        raise ValueError("DART structured data is available for fiscal years 2015 onward.")
    return str(year)


def corp_header(corp: Corp) -> dict[str, Any]:
    return {"company": corp.name_en or corp.name_ko, "company_ko": corp.name_ko, "ticker": corp.stock_code or None}


def filing_row(row: dict[str, Any]) -> dict[str, Any]:
    rm = row.get("rm") or ""
    return {
        "date": fmt_date(row.get("rcept_dt")),
        "title_ko": row.get("report_nm", "").strip(),
        "title_en": glossary.translate_report_name(row.get("report_nm", "")),
        "company_ko": row.get("corp_name"),
        "ticker": row.get("stock_code") or None,
        "market": glossary.CORP_CLASS.get(row.get("corp_cls", "")),
        "filer": row.get("flr_nm"),
        "flags": [glossary.REMARK_FLAGS.get(ch, ch) for ch in rm if not ch.isspace()] or None,
        "rcept_no": row.get("rcept_no"),
        "url": VIEWER_URL.format(row.get("rcept_no")),
    }


# --- Tools ------------------------------------------------------------------


@mcp.tool(annotations=READ_ONLY)
@tool_errors
async def search_company(query: str, limit: int = 10, listed_only: bool = False) -> list[dict[str, Any]]:
    """Find Korean companies on DART by English name, Korean name, KRX ticker, or corp_code.

    Use this first when unsure which entity a name refers to (e.g. "Samsung" matches
    dozens of group companies). Listed companies rank first.
    """
    index = await service.index()
    return [c.to_dict() for c in index.search(query, limit=max(1, min(limit, 50)), listed_only=listed_only)]


@mcp.tool(annotations=READ_ONLY)
@tool_errors
async def get_company_profile(company: str) -> dict[str, Any]:
    """Company overview: English/Korean name, CEO, market, industry code, address, website, fiscal year-end.

    `company` accepts a ticker (005930), corp_code, or name.
    """
    corp = await service.resolve(company)
    d = await service.client.get_json("company.json", corp_code=corp.corp_code)
    return {
        "corp_code": corp.corp_code,
        "name_en": d.get("corp_name_eng") or corp.name_en or None,
        "name_ko": d.get("corp_name"),
        "ticker": d.get("stock_code") or None,
        "market": glossary.CORP_CLASS.get(d.get("corp_cls", ""), d.get("corp_cls")),
        "ceo_ko": d.get("ceo_nm"),
        "industry_code_ksic": d.get("induty_code"),
        "established": fmt_date(d.get("est_dt")),
        "fiscal_year_end_month": d.get("acc_mt"),
        "address_ko": d.get("adres"),
        "website": d.get("hm_url") or None,
        "ir_website": d.get("ir_url") or None,
        "phone": d.get("phn_no") or None,
        "business_registration_no": d.get("bizr_no") or None,
        "corporate_registration_no": d.get("jurir_no") or None,
    }


FilingType = Literal[
    "periodic", "major_event", "issuance", "ownership", "other", "audit", "fund", "abs", "exchange", "ftc"
]
Market = Literal["kospi", "kosdaq", "konex", "other"]
_MARKET_CODES = {"kospi": "Y", "kosdaq": "K", "konex": "N", "other": "E"}

# DART caps market-wide list.json searches at roughly 3 months, so longer ranges are split.
MARKET_WINDOW_DAYS = 90
MAX_LIST_PAGES = 30


def date_range(days: int, start_date: str | None, end_date: str | None) -> tuple[str, str]:
    end = parse_date(end_date, "end_date") or date.today().strftime("%Y%m%d")
    start = parse_date(start_date, "start_date") or (
        datetime.strptime(end, "%Y%m%d") - timedelta(days=max(1, days))
    ).strftime("%Y%m%d")
    if start > end:
        raise ValueError("start_date must be on or before end_date.")
    return start, end


def windows(start: str, end: str, span_days: int) -> list[tuple[str, str]]:
    """Split [start, end] into consecutive windows, newest first."""
    lo = datetime.strptime(start, "%Y%m%d")
    hi = datetime.strptime(end, "%Y%m%d")
    out = []
    while hi >= lo:
        w_lo = max(lo, hi - timedelta(days=span_days - 1))
        out.append((w_lo.strftime("%Y%m%d"), hi.strftime("%Y%m%d")))
        hi = w_lo - timedelta(days=1)
    return out


async def collect_filings(params: dict[str, Any], start: str, end: str, limit: int) -> tuple[list[dict], int, bool]:
    """Fetch filings newest first across pages (and 90-day windows when market-wide).

    Returns (rows, total_reported_by_dart, truncated).
    """
    spans = [(start, end)] if "corp_code" in params else windows(start, end, MARKET_WINDOW_DAYS)
    rows: list[dict] = []
    total = 0
    pages = 0
    for i, (w_start, w_end) in enumerate(spans):
        page = 1
        while True:
            d = await service.client.get_json(
                "list.json", **params, bgn_de=w_start, end_de=w_end, page_no=page, page_count=100
            )
            pages += 1
            if page == 1:
                total += d.get("total_count", 0)
            rows.extend(d.get("list", []))
            more = page < d.get("total_page", 0) or i < len(spans) - 1
            if len(rows) >= limit or pages >= MAX_LIST_PAGES:
                return rows[:limit], total, len(rows) > limit or more
            if page >= d.get("total_page", 0):
                break
            page += 1
    return rows, total, False


# Ownership filings (type D) can number in the thousands per year at large companies
# (one per executive stock grant), so they are capped separately from material filings.
OWNERSHIP_SCAN_CAP = 200


async def collect_company_filings(corp: Corp, start: str, end: str) -> tuple[list[dict], bool]:
    """All filing types for one company, newest first, with ownership filings capped."""
    types = [code for code, _ in glossary.FILING_TYPES.values()]

    async def one(code: str) -> tuple[list[dict], bool]:
        params = list_params(corp, None, None, False) | {"pblntf_ty": code}
        rows, _, truncated = await collect_filings(params, start, end, OWNERSHIP_SCAN_CAP if code == "D" else 1000)
        return rows, truncated

    results = await asyncio.gather(*(one(code) for code in types))
    rows = sorted((r for chunk, _ in results for r in chunk), key=lambda r: r.get("rcept_no", ""), reverse=True)
    return rows, any(t for _, t in results)


def list_params(
    corp: Corp | None, filing_type: str | None, market: str | None, include_amended_originals: bool
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "last_reprt_at": "N" if include_amended_originals else "Y",
        "sort": "date",
        "sort_mth": "desc",
    }
    if corp:
        params["corp_code"] = corp.corp_code
    if filing_type:
        params["pblntf_ty"] = glossary.FILING_TYPES[filing_type][0]
    if market:
        params["corp_cls"] = _MARKET_CODES[market]
    return params


@mcp.tool(annotations=READ_ONLY)
@tool_errors
async def get_recent_filings(
    company: str | None = None,
    days: int = 30,
    filing_type: FilingType | None = None,
    market: Market | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    include_amended_originals: bool = False,
    limit: int = 30,
) -> dict[str, Any]:
    """List DART filings, newest first, with English titles where known.

    - company: ticker / corp_code / name. Omit to search the whole market (long ranges are
      split into 90-day windows automatically).
    - filing_type: periodic (annual/quarterly reports), major_event (M&A, capital raises,
      litigation), issuance, ownership (5% block / insider), other, audit, fund, abs,
      exchange (preliminary earnings, KRX inquiries), ftc.
    - market: kospi, kosdaq, konex, other.
    - start_date / end_date (YYYY-MM-DD) override `days`. limit: up to 500.
    For a red-flag digest use get_material_events. To read a filing use get_filing_text.
    """
    start, end = date_range(days, start_date, end_date)
    corp = await service.resolve(company) if company else None
    params = list_params(corp, filing_type, market, include_amended_originals)
    rows, total, truncated = await collect_filings(params, start, end, max(1, min(limit, 500)))
    return {
        **(corp_header(corp) if corp else {}),
        "range": f"{fmt_date(start)} to {fmt_date(end)}",
        "total": total,
        "returned": len(rows),
        "truncated": truncated,
        "filings": [filing_row(r) for r in rows],
    }


EventCategory = Literal[
    "distress",
    "control_change",
    "dilution",
    "exchange_scrutiny",
    "litigation",
    "capital_reduction",
    "m_and_a",
    "capital_return",
    "earnings",
    "large_contract",
    "governance",
    "ownership",
    "periodic",
    "other",
]


@mcp.tool(annotations=READ_ONLY)
@tool_errors
async def get_material_events(
    company: str | None = None,
    days: int = 180,
    min_severity: Literal["info", "notable", "warning", "critical"] = "notable",
    categories: list[EventCategory] | None = None,
    market: Market | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """What happened, and should I worry? Material events classified in English, with red flags.

    Classifies filings into categories (distress, control_change, dilution [CB/BW/rights
    offerings], exchange_scrutiny, litigation, m_and_a, capital_return [buybacks/dividends],
    earnings, large_contract, governance, ...) with a severity and a plain-English reason.
    For a single company it also returns `red_flags`: Korea-specific warning patterns such
    as serial convertible bond issuance, conversion price resets, and frequent amendments.

    Omit `company` to scan the whole market, e.g. categories=["dilution"], market="kosdaq",
    days=30 finds recent CB/BW/rights issues on KOSDAQ.
    """
    start, end = date_range(days, start_date, end_date)
    corp = await service.resolve(company) if company else None
    if corp:
        rows, truncated = await collect_company_filings(corp, start, end)
    else:
        rows, _, truncated = await collect_filings(list_params(None, None, market, False), start, end, 3000)

    wanted = set(categories or [])
    floor = analysis.SEVERITY_ORDER[min_severity]
    events: list[dict[str, Any]] = []
    for r in rows:
        title = r.get("report_nm", "")
        category, severity, why = analysis.classify_filing(title)
        events.append(
            {
                **filing_row(r),
                "category": category,
                "severity": severity,
                "why_it_matters": why,
                "amended": analysis.is_amendment(title),
            }
        )

    window = (datetime.strptime(end, "%Y%m%d") - datetime.strptime(start, "%Y%m%d")).days + 1
    matching = [
        e for e in events if analysis.SEVERITY_ORDER[e["severity"]] >= floor and (not wanted or e["category"] in wanted)
    ]
    out: dict[str, Any] = {
        **(corp_header(corp) if corp else {}),
        "range": f"{fmt_date(start)} to {fmt_date(end)}",
        "filings_scanned": len(events),
        "scan_truncated": truncated,
        "counts_by_category": dict(Counter(e["category"] for e in events).most_common()),
        "events": matching[: max(1, min(limit, 300))],
        "events_matching": len(matching),
    }
    if corp:
        out["red_flags"] = analysis.red_flags(events, window)
    return out


@mcp.tool(annotations=READ_ONLY)
@tool_errors
async def get_filing_text(
    rcept_no: str,
    section: str | None = None,
    offset: int = 0,
    max_chars: int = 20_000,
    search: str | None = None,
) -> dict[str, Any]:
    """Read the original text of a filing (Korean) by its 14-digit rcept_no.

    - section: jump to a part of the report by English name: overview, business, products,
      risk_factors, mdna, financials, notes, dividends, audit, board, shareholders,
      executives, compensation, affiliates, related_party, litigation, investor_protection.
      A Korean heading keyword also works. `offset` then pages within the section.
    - search: a Korean keyword (매출, 배당, 최대주주, 소송, 전환사채) returns matching snippets.
    - Otherwise returns the document from `offset`, plus a table of contents on the first page.
    Tables are flattened to ' | '-separated rows. Translate as needed and cite `url`.
    """
    if not re.fullmatch(r"\d{14}", rcept_no):
        raise ValueError("rcept_no must be the 14-digit receipt number from get_recent_filings.")
    doc = await service.document(rcept_no)
    base = {"rcept_no": rcept_no, "url": VIEWER_URL.format(rcept_no), "total_chars": len(doc.text)}
    if search:
        return {**base, "search": search, "matches": find_snippets(doc.text, search)}
    text = doc.text
    if section:
        found = extract_section(doc, section)
        if found is None:
            raise LookupError(
                f"Section {section!r} not found in this filing. Known aliases: {', '.join(SECTION_ALIASES)}. "
                f"Headings in this filing: {[t['title'] for t in doc.toc[:40]]}"
            )
        base["section"], text = found
        base["section_chars"] = len(text)
    offset = max(0, offset)
    size = max(1_000, min(max_chars, MAX_DOC_CHARS))
    chunk = text[offset : offset + size]
    next_offset = offset + len(chunk)
    return {
        **base,
        "toc": doc.toc if offset == 0 and not section else None,
        "offset": offset,
        "next_offset": next_offset if next_offset < len(text) else None,
        "text": chunk,
    }


def _fs_row(r: dict[str, Any]) -> dict[str, Any]:
    row = {
        "account_en": glossary.account_label(r.get("account_id"), r.get("account_nm", "")),
        "account_ko": r.get("account_nm"),
        "current": parse_amount(r.get("thstrm_amount")),
        "prior": parse_amount(r.get("frmtrm_amount")),
    }
    if r.get("bfefrmtrm_amount"):
        row["two_years_prior"] = parse_amount(r.get("bfefrmtrm_amount"))
    if r.get("thstrm_add_amount"):
        row["current_year_to_date"] = parse_amount(r.get("thstrm_add_amount"))
    if r.get("account_id") and r["account_id"] != "-표준계정코드 미사용-":
        row["xbrl_id"] = r["account_id"]
    return row


async def fetch_statements(
    corp: Corp, year: int, period: str, consolidated: bool, detail: str
) -> tuple[list[dict[str, Any]], str, bool]:
    """Return (rows, basis, used_fallback), preferring the requested consolidation basis."""
    params = {"corp_code": corp.corp_code, "bsns_year": check_year(year), "reprt_code": report_code(period)}
    order = ["CFS", "OFS"] if consolidated else ["OFS", "CFS"]
    for basis in order:
        if detail == "full":
            d = await service.client.get_json("fnlttSinglAcntAll.json", fs_div=basis, **params)
            rows = d.get("list", [])
        else:
            d = await service.client.get_json("fnlttSinglAcnt.json", **params)
            rows = [r for r in d.get("list", []) if r.get("fs_div") == basis]
        if rows:
            return rows, basis, basis != order[0]
    raise LookupError(
        f"No XBRL financial statements for {corp.name_en or corp.name_ko} {year} {period}. "
        "The report may not be filed yet, or the company (e.g. some financial firms, unlisted "
        "entities) does not file XBRL. Try get_recent_filings with filing_type='periodic' "
        "and read the report with get_filing_text."
    )


@mcp.tool(annotations=READ_ONLY)
@tool_errors
async def get_financial_statements(
    company: str,
    year: int,
    period: Literal["annual", "half", "q1", "q3"] = "annual",
    consolidated: bool = True,
    detail: Literal["summary", "full"] = "summary",
) -> dict[str, Any]:
    """Financial statements from XBRL filings, with English account labels.

    - year: fiscal year (2015+). period: annual, half (H1), q1, q3. For Q4/full-year use annual.
    - consolidated: True = consolidated (CFS); falls back to separate (OFS) if the company
      files no consolidated statements.
    - detail: summary = key accounts (revenue, operating profit, net income, assets,
      liabilities, equity); full = every line of BS, IS, CIS, CF, SCE.
    Amounts are integers in KRW (won). 'current' is the reported period; for quarterly
    income statements 'current' is the 3-month quarter and 'current_year_to_date' is cumulative.
    `key_metrics` gives revenue growth, operating/net margin, ROE and debt-to-equity in percent
    (not annualized for quarters).
    """
    corp = await service.resolve(company)
    rows, basis, fallback = await fetch_statements(corp, year, period, consolidated, detail)
    statements: dict[str, dict[str, Any]] = {}
    for r in rows:
        sj = r.get("sj_div", "")
        st = statements.setdefault(
            sj,
            {
                "statement_en": glossary.STATEMENT_TYPES.get(sj, sj),
                "statement_ko": r.get("sj_nm"),
                "periods": {
                    "current": r.get("thstrm_nm"),
                    "prior": r.get("frmtrm_nm"),
                    "two_years_prior": r.get("bfefrmtrm_nm") or None,
                },
                "lines": [],
            },
        )
        st["lines"].append(_fs_row(r))

    first = rows[0]
    return {
        **corp_header(corp),
        "fiscal_year": year,
        "period": glossary.REPORT_CODE_NAMES[report_code(period)],
        "basis": glossary.FS_DIV[basis],
        "basis_fallback": fallback,
        "currency": first.get("currency") or "KRW",
        "unit": "won",
        "source_filing": VIEWER_URL.format(first.get("rcept_no")) if first.get("rcept_no") else None,
        "key_metrics": analysis.key_metrics([line for st in statements.values() for line in st["lines"]]),
        "statements": list(statements.values()),
    }


@mcp.tool(annotations=READ_ONLY)
@tool_errors
async def compare_companies(
    companies: list[str],
    year: int,
    period: Literal["annual", "half", "q1", "q3"] = "annual",
    consolidated: bool = True,
) -> dict[str, Any]:
    """Side-by-side key metrics for up to 10 companies: revenue, profit, growth, margins, ROE, leverage.

    Use for peer comparisons, e.g. ["Samsung Electronics", "SK hynix"]. Amounts in KRW (won).
    Companies without XBRL data for the period are listed under `unavailable`.
    """
    if not 1 <= len(companies) <= 10:
        raise ValueError("Pass between 1 and 10 companies.")
    corps = [await service.resolve(c) for c in companies]

    async def one(corp: Corp) -> dict[str, Any]:
        try:
            rows, basis, _ = await fetch_statements(corp, year, period, consolidated, "summary")
        except LookupError as exc:
            return {**corp_header(corp), "error": str(exc)}
        return {
            **corp_header(corp),
            "basis": glossary.FS_DIV[basis],
            **analysis.key_metrics([_fs_row(r) for r in rows]),
        }

    results = await asyncio.gather(*(one(c) for c in corps))
    return {
        "fiscal_year": year,
        "period": glossary.REPORT_CODE_NAMES[report_code(period)],
        "currency": "KRW",
        "companies": [r for r in results if "error" not in r],
        "unavailable": [r for r in results if "error" in r],
    }


@mcp.tool(annotations=READ_ONLY)
@tool_errors
async def get_major_shareholder_changes(company: str, limit: int = 20) -> dict[str, Any]:
    """5% block-holding reports (대량보유상황보고): who crossed or changed a 5%+ stake.

    Korea's equivalent of SEC Schedule 13D/13G. Shows filer, shares held, ownership %,
    change vs. prior report, and stated reason. Newest first.
    """
    corp = await service.resolve(company)
    d = await service.client.get_json("majorstock.json", corp_code=corp.corp_code)
    items = sorted(d.get("list", []), key=lambda r: r.get("rcept_no", ""), reverse=True)
    return {
        **corp_header(corp),
        "total_reports": len(items),
        "reports": [
            {
                "date": fmt_date(r.get("rcept_dt")),
                "filer_ko": r.get("repror"),
                "report_type_ko": r.get("report_tp"),
                "report_type_en": glossary.BLOCK_REPORT_TYPES.get((r.get("report_tp") or "").strip()),
                "shares_held": parse_amount(r.get("stkqy")),
                "shares_change": parse_amount(r.get("stkqy_irds")),
                "ownership_pct": parse_amount(r.get("stkrt")),
                "ownership_pct_change": parse_amount(r.get("stkrt_irds")),
                "contractual_shares": parse_amount(r.get("ctr_stkqy")),
                "contractual_pct": parse_amount(r.get("ctr_stkrt")),
                "reason_ko": r.get("report_resn"),
                "url": VIEWER_URL.format(r.get("rcept_no")),
            }
            for r in items[: max(1, min(limit, 100))]
        ],
    }


@mcp.tool(annotations=READ_ONLY)
@tool_errors
async def get_insider_trades(company: str, days: int = 365, limit: int = 20) -> dict[str, Any]:
    """Executive and major-shareholder ownership reports (임원ㆍ주요주주 소유보고).

    Korea's equivalent of SEC Form 4: holdings and changes by directors, officers, and
    10%+ holders. `summary` gives share-count totals for the last `days`, separately for
    key insiders (registered directors and 10%+ holders) and for all filers. Changes include
    grants, option exercises, inheritance and gifts; open a report's url for the reason.
    Reports newest first.
    """
    corp = await service.resolve(company)
    d = await service.client.get_json("elestock.json", corp_code=corp.corp_code)
    cutoff = (date.today() - timedelta(days=max(1, days))).strftime("%Y%m%d")
    items = sorted(
        (r for r in d.get("list", []) if (r.get("rcept_dt") or "") >= cutoff),
        key=lambda r: r.get("rcept_no", ""),
        reverse=True,
    )
    reports = [
        {
            "date": fmt_date(r.get("rcept_dt")),
            "insider_ko": r.get("repror"),
            "registered_executive_ko": r.get("isu_exctv_rgist_at"),
            "position_ko": r.get("isu_exctv_ofcps"),
            "major_shareholder_ko": r.get("isu_main_shrholdr"),
            "shares_held": parse_amount(r.get("sp_stock_lmp_cnt")),
            "shares_change": parse_amount(r.get("sp_stock_lmp_irds_cnt")),
            "ownership_pct": parse_amount(r.get("sp_stock_lmp_rate")),
            "ownership_pct_change": parse_amount(r.get("sp_stock_lmp_irds_rate")),
            "url": VIEWER_URL.format(r.get("rcept_no")),
        }
        for r in items
    ]
    return {
        **corp_header(corp),
        "window_days": days,
        "total_reports": len(reports),
        "summary": analysis.insider_summary(reports),
        "reports": reports[: max(1, min(limit, 100))],
    }


@mcp.tool(annotations=READ_ONLY)
@tool_errors
async def get_largest_shareholders(
    company: str, year: int, period: Literal["annual", "half", "q1", "q3"] = "annual"
) -> dict[str, Any]:
    """Largest shareholder and related parties as of a periodic report (최대주주 현황).

    Reveals chaebol control structure: founding family, affiliates, foundations, and
    their stakes at the start and end of the period.
    """
    corp = await service.resolve(company)
    d = await service.client.get_json(
        "hyslrSttus.json", corp_code=corp.corp_code, bsns_year=check_year(year), reprt_code=report_code(period)
    )
    holders = []
    for r in d.get("list", []):
        relation = (r.get("relate") or "").strip()
        kind = (r.get("stock_knd") or "").strip()
        holders.append(
            {
                "name_ko": r.get("nm"),
                "relation_ko": relation or None,
                "relation_en": glossary.relation_label(relation),
                "share_class_ko": kind or None,
                "share_class_en": glossary.STOCK_KINDS.get(kind.replace(" ", "")),
                "shares_start": parse_amount(r.get("bsis_posesn_stock_co")),
                "pct_start": parse_amount(r.get("bsis_posesn_stock_qota_rt")),
                "shares_end": parse_amount(r.get("trmend_posesn_stock_co")),
                "pct_end": parse_amount(r.get("trmend_posesn_stock_qota_rt")),
                "note_ko": r.get("rm") if r.get("rm") not in (None, "-") else None,
            }
        )
    return {
        **corp_header(corp),
        "fiscal_year": year,
        "period": glossary.REPORT_CODE_NAMES[report_code(period)],
        "holders": holders,
    }


@mcp.tool(annotations=READ_ONLY)
@tool_errors
async def get_dividends(
    company: str, year: int, period: Literal["annual", "half", "q1", "q3"] = "annual"
) -> dict[str, Any]:
    """Dividend data from a periodic report: DPS, payout ratio, yield, total paid (배당에 관한 사항).

    Labels are Korean (e.g. 주당 현금배당금(원) = cash dividend per share in won,
    현금배당성향(%) = payout ratio, 현금배당수익률(%) = dividend yield).
    """
    corp = await service.resolve(company)
    d = await service.client.get_json(
        "alotMatter.json", corp_code=corp.corp_code, bsns_year=check_year(year), reprt_code=report_code(period)
    )
    return {
        **corp_header(corp),
        "fiscal_year": year,
        "items": [
            {
                "item_ko": r.get("se"),
                "share_class_ko": r.get("stock_knd") or None,
                "current": parse_amount(r.get("thstrm")),
                "prior": parse_amount(r.get("frmtrm")),
                "two_years_prior": parse_amount(r.get("lwfr")),
            }
            for r in d.get("list", [])
        ],
    }


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
async def translate_terms(terms: list[str]) -> dict[str, str | None]:
    """Look up Korean disclosure, accounting, and governance terms in a curated glossary.

    More reliable than generic translation for DART jargon (e.g. 유상증자, 최대주주,
    전환사채, 공정공시, 기재정정). Returns null for unknown terms. No API call needed.
    """
    return glossary.lookup_terms(terms[:200])


@mcp.resource("dart://glossary/filing-types")
def filing_types_resource() -> str:
    """DART filing categories and their English meanings."""
    return "\n".join(f"{k} ({code}): {desc}" for k, (code, desc) in glossary.FILING_TYPES.items())


KOREA_PRIMER = """\
# Reading Korean corporate filings: a primer for foreign analysts

## The system
- DART (dart.fss.or.kr) is run by the Financial Supervisory Service (FSS), Korea's SEC
  counterpart. Every listed company and large unlisted company files here.
- Markets: KOSPI (main board, large caps), KOSDAQ (growth/tech, smaller, more retail-driven),
  KONEX (startups). Tickers are 6 digits; preferred shares usually end in 5 (005935).
- Almost everything is in Korean only. English filings are voluntary and rare.

## Filings that map to US equivalents
- 사업보고서 Annual Report ≈ 10-K (due 90 days after fiscal year-end; most FYs end in December)
- 반기/분기보고서 Half-year/Quarterly Report ≈ 10-Q. There is no Q4 report; use the annual.
- 주요사항보고서 Major Matters Report and exchange disclosures ≈ 8-K
- 주식등의대량보유상황보고서 5% Block Holding Report ≈ 13D/13G (filed within 5 business days)
- 임원ㆍ주요주주 소유상황보고서 Insider Ownership Report ≈ Form 4
- 증권신고서 / 투자설명서 Registration Statement / Prospectus ≈ S-1 / 424B

## Things that surprise foreign investors
- Chaebol: family-controlled groups (Samsung, SK, LG and others) control dozens of listed and
  unlisted affiliates through cross-holdings, often with a small direct family stake.
  "Largest shareholder" (최대주주) includes related parties (특수관계인) as a bloc.
- Consolidated (연결) vs separate (별도) statements: holding companies look very different on
  each basis. Dividends are often set from separate earnings.
- Convertible bonds (CB) with conversion-price refixing (리픽싱) are common at KOSDAQ small caps
  and are a frequent source of dilution.
- Spin-offs (물적분할) where the parent keeps all shares of the new company have historically
  hurt minority shareholders.
- The "Corporate Value-up" program (기업가치제고계획, 2024~) encourages buybacks, cancellations,
  and higher payouts to close the "Korea discount".
- Numbers: 억 = 100 million, 조 = 1 trillion. Filings often report in 백만원 (millions of won).
  This server returns raw won.
- Korean names: family name first (이재용 = Lee Jae-yong). Romanization varies between sources.
"""


@mcp.resource("dart://guide/korea-primer")
def korea_primer() -> str:
    """Primer on Korean disclosure rules, markets and pitfalls for foreign analysts."""
    return KOREA_PRIMER


@mcp.prompt()
def company_brief(company: str) -> str:
    """English investment brief on a Korean company from its DART filings."""
    return (
        f"Write an English brief on {company} using the DART tools. Steps: "
        "1) get_company_profile; 2) get_financial_statements (summary) for the latest fiscal year "
        "and use key_metrics; 3) get_material_events for the last 180 days and explain any "
        "red_flags; 4) get_largest_shareholders, get_major_shareholder_changes and "
        "get_insider_trades for ownership and insider holdings; 5) get_filing_text with "
        "section='business' on the latest annual report for what the company actually does. "
        "Cite filing URLs. Note anything you translated yourself."
    )


# --- Entry point --------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="DART MCP server")
    parser.add_argument("--transport", choices=["stdio", "sse", "streamable-http"], default="stdio")
    parser.add_argument("--host", default=os.environ.get("DART_MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("DART_MCP_PORT", "8000")))
    args = parser.parse_args()

    # stdout is the MCP channel on stdio; logs must go to stderr.
    logging.basicConfig(
        level=os.environ.get("DART_MCP_LOG_LEVEL", "INFO"),
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not os.environ.get("DART_API_KEY"):
        log.error("DART_API_KEY is not set; tools will fail until it is provided.")
    if args.transport == "stdio":
        mcp.run()
    else:
        mcp.run(transport=args.transport, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
