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
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from typing import Any, Literal, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import glossary
from .client import DartClient, DartError
from .corp_codes import Corp, CorpIndex, load_corp_index
from .document import FilingDocument, find_snippets, parse_document_zip

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
        "`currency` field says otherwise. Always cite `url` links to the original filing."
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


@mcp.tool()
@tool_errors
async def search_company(query: str, limit: int = 10, listed_only: bool = False) -> list[dict[str, Any]]:
    """Find Korean companies on DART by English name, Korean name, KRX ticker, or corp_code.

    Use this first when unsure which entity a name refers to (e.g. "Hyundai" matches
    dozens of group companies). Listed companies rank first.
    """
    index = await service.index()
    return [c.to_dict() for c in index.search(query, limit=max(1, min(limit, 50)), listed_only=listed_only)]


@mcp.tool()
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


@mcp.tool()
@tool_errors
async def get_recent_filings(
    company: str | None = None,
    days: int = 30,
    filing_type: FilingType | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    include_amended_originals: bool = False,
    limit: int = 20,
    page: int = 1,
) -> dict[str, Any]:
    """List DART filings, newest first, with English titles where known.

    - company: ticker / corp_code / name. Omit to see the whole market (DART limits
      market-wide searches to a 3-month window).
    - filing_type: periodic (annual/quarterly reports), major_event (M&A, capital raises,
      litigation), issuance, ownership (5% block / insider), other, audit, fund, abs,
      exchange (preliminary earnings, KRX inquiries), ftc.
    - start_date / end_date (YYYY-MM-DD) override `days`.
    Use get_filing_text with a returned rcept_no to read the filing body.
    """
    end = parse_date(end_date, "end_date") or date.today().strftime("%Y%m%d")
    start = parse_date(start_date, "start_date") or (
        datetime.strptime(end, "%Y%m%d") - timedelta(days=max(1, days))
    ).strftime("%Y%m%d")
    params: dict[str, Any] = {
        "bgn_de": start,
        "end_de": end,
        "last_reprt_at": "N" if include_amended_originals else "Y",
        "page_no": max(1, page),
        "page_count": max(1, min(limit, 100)),
        "sort": "date",
        "sort_mth": "desc",
    }
    corp = None
    if company:
        corp = await service.resolve(company)
        params["corp_code"] = corp.corp_code
    if filing_type:
        params["pblntf_ty"] = glossary.FILING_TYPES[filing_type][0]
    d = await service.client.get_json("list.json", **params)
    return {
        **(corp_header(corp) if corp else {}),
        "range": f"{fmt_date(start)} to {fmt_date(end)}",
        "total": d.get("total_count", 0),
        "page": d.get("page_no", 1),
        "total_pages": d.get("total_page", 0),
        "filings": [filing_row(r) for r in d.get("list", [])],
    }


@mcp.tool()
@tool_errors
async def get_filing_text(
    rcept_no: str, offset: int = 0, max_chars: int = 20_000, search: str | None = None
) -> dict[str, Any]:
    """Read the original text of a filing (Korean) by its 14-digit rcept_no.

    Returns a table of contents with character offsets; page through long filings with
    `offset`. Pass `search` (a Korean keyword such as 매출, 배당, 최대주주, 소송) to get
    matching snippets instead of a page. Tables are flattened to ' | '-separated rows.
    Translate the returned text as needed and cite `url`.
    """
    if not re.fullmatch(r"\d{14}", rcept_no):
        raise ValueError("rcept_no must be the 14-digit receipt number from get_recent_filings.")
    doc = await service.document(rcept_no)
    base = {"rcept_no": rcept_no, "url": VIEWER_URL.format(rcept_no), "total_chars": len(doc.text)}
    if search:
        return {**base, "search": search, "matches": find_snippets(doc.text, search)}
    offset = max(0, offset)
    size = max(1_000, min(max_chars, MAX_DOC_CHARS))
    chunk = doc.text[offset : offset + size]
    next_offset = offset + len(chunk)
    return {
        **base,
        "toc": doc.toc if offset == 0 else None,
        "offset": offset,
        "next_offset": next_offset if next_offset < len(doc.text) else None,
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


@mcp.tool()
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
    """
    corp = await service.resolve(company)
    params = {"corp_code": corp.corp_code, "bsns_year": check_year(year), "reprt_code": report_code(period)}
    order = ["CFS", "OFS"] if consolidated else ["OFS", "CFS"]

    rows: list[dict[str, Any]] = []
    basis = order[0]
    for basis in order:
        if detail == "full":
            d = await service.client.get_json("fnlttSinglAcntAll.json", fs_div=basis, **params)
            rows = d.get("list", [])
        else:
            d = await service.client.get_json("fnlttSinglAcnt.json", **params)
            rows = [r for r in d.get("list", []) if r.get("fs_div") == basis]
        if rows:
            break
    if not rows:
        raise LookupError(
            f"No XBRL financial statements for {corp.name_en or corp.name_ko} {year} {period}. "
            "The report may not be filed yet, or the company (e.g. some financial firms, unlisted "
            "entities) does not file XBRL. Try get_recent_filings with filing_type='periodic' "
            "and read the report with get_filing_text."
        )

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
        "period": glossary.REPORT_CODE_NAMES[params["reprt_code"]],
        "basis": glossary.FS_DIV[basis],
        "basis_fallback": basis != order[0],
        "currency": first.get("currency") or "KRW",
        "unit": "won",
        "source_filing": VIEWER_URL.format(first.get("rcept_no")) if first.get("rcept_no") else None,
        "statements": list(statements.values()),
    }


@mcp.tool()
@tool_errors
async def get_major_shareholder_changes(company: str, limit: int = 20) -> dict[str, Any]:
    """5% block-holding reports (대량보유상황보고): who crossed or changed a 5%+ stake.

    Korea's equivalent of SEC Schedule 13D/13G. Shows filer, shares held, ownership %,
    change vs. prior report, and stated reason. Newest first. Key activist/M&A signal.
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


@mcp.tool()
@tool_errors
async def get_insider_trades(company: str, limit: int = 20) -> dict[str, Any]:
    """Executive and major-shareholder ownership reports (임원ㆍ주요주주 소유보고).

    Korea's equivalent of SEC Form 4: holdings and changes by directors, officers, and
    10%+ holders. Newest first.
    """
    corp = await service.resolve(company)
    d = await service.client.get_json("elestock.json", corp_code=corp.corp_code)
    items = sorted(d.get("list", []), key=lambda r: r.get("rcept_no", ""), reverse=True)
    return {
        **corp_header(corp),
        "total_reports": len(items),
        "reports": [
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
            for r in items[: max(1, min(limit, 100))]
        ],
    }


@mcp.tool()
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
                "relation_en": glossary.RELATIONS.get(relation.replace(" ", "")),
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


@mcp.tool()
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


@mcp.tool()
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


@mcp.prompt()
def company_brief(company: str) -> str:
    """English investment brief on a Korean company from its DART filings."""
    return (
        f"Write an English brief on {company} using the DART tools. Steps: "
        "1) get_company_profile; 2) get_financial_statements for the latest two fiscal years "
        "(summary) and compute growth and margins; 3) get_recent_filings for the last 90 days "
        "and flag material events (capital raises, CBs, M&A, litigation, largest-shareholder "
        "changes); 4) get_largest_shareholders and get_major_shareholder_changes for control "
        "and activist signals. Cite filing URLs. Note anything you translated yourself."
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
