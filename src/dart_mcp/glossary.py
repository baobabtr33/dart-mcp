"""Korean-to-English glossary for DART codes, filing titles, and accounting terms.

This module is the core value-add for non-Korean users: DART returns Korean
labels and terse codes, and generic machine translation gets many of these
wrong (e.g. 유상증자 is a paid-in capital increase / rights offering, not
"paid increase"). Deterministic mappings here are returned alongside the
original Korean so the calling LLM can verify or refine them.
"""

from __future__ import annotations

import re

# --- Codes -----------------------------------------------------------------

REPORT_CODES: dict[str, str] = {
    "annual": "11011",
    "half": "11012",
    "q1": "11013",
    "q3": "11014",
}
REPORT_CODE_NAMES = {
    "11011": "Annual report (FY)",
    "11012": "Half-year report (H1)",
    "11013": "Q1 report",
    "11014": "Q3 report",
}

FILING_TYPES: dict[str, tuple[str, str]] = {
    # key: (DART pblntf_ty, description)
    "periodic": ("A", "Periodic reports: annual, half-year, quarterly"),
    "major_event": ("B", "Major matters reports: M&A, capital raises, defaults, litigation"),
    "issuance": ("C", "Securities issuance: registration statements, prospectuses"),
    "ownership": ("D", "Ownership: 5% block holdings, insider ownership, tender offers"),
    "other": ("E", "Other disclosures: treasury stock, mergers by small companies"),
    "audit": ("F", "External audit reports"),
    "fund": ("G", "Fund disclosures"),
    "abs": ("H", "Asset-backed securities"),
    "exchange": ("I", "Exchange (KRX) disclosures: preliminary earnings, inquiries, fair disclosure"),
    "ftc": ("J", "Fair Trade Commission disclosures (large business groups)"),
}

CORP_CLASS = {
    "Y": "KOSPI (main board)",
    "K": "KOSDAQ",
    "N": "KONEX",
    "E": "Other / unlisted",
}

STATEMENT_TYPES = {
    "BS": "Balance sheet",
    "IS": "Income statement",
    "CIS": "Statement of comprehensive income",
    "CF": "Cash flow statement",
    "SCE": "Statement of changes in equity",
}

FS_DIV = {"CFS": "Consolidated", "OFS": "Separate (parent-only)"}

# `rm` flags on filing list rows.
REMARK_FLAGS = {
    "유": "KOSPI market division filing",
    "코": "KOSDAQ market division filing",
    "채": "Bond listing filing",
    "넥": "KONEX market division filing",
    "공": "Fair Trade Commission filing",
    "연": "Includes consolidated data",
    "정": "Later amended (a correction was filed)",
    "철": "Withdrawn",
}

# --- Filing titles ---------------------------------------------------------
# Matched as substrings (whitespace-insensitive), longest first.

REPORT_TITLES: dict[str, str] = {
    "사업보고서": "Annual Report",
    "반기보고서": "Half-Year Report",
    "분기보고서": "Quarterly Report",
    "감사보고서": "Audit Report",
    "연결감사보고서": "Consolidated Audit Report",
    "주요사항보고서": "Major Matters Report",
    "증권신고서": "Securities Registration Statement",
    "투자설명서": "Prospectus",
    "일괄신고추가서류": "Shelf Registration Supplement",
    "증권발행실적보고서": "Securities Issuance Results Report",
    "주식등의대량보유상황보고서": "5% Block Holding Report (Large Shareholding)",
    "임원ㆍ주요주주특정증권등소유상황보고서": "Insider Ownership Report (Executives & Major Shareholders)",
    "임원·주요주주특정증권등소유상황보고서": "Insider Ownership Report (Executives & Major Shareholders)",
    "최대주주등소유주식변동신고서": "Largest Shareholder Ownership Change Report",
    "최대주주변경": "Change of Largest Shareholder",
    "공개매수신고서": "Tender Offer Statement",
    "영업(잠정)실적(공정공시)": "Preliminary Earnings (Fair Disclosure)",
    "연결재무제표기준영업(잠정)실적(공정공시)": "Preliminary Consolidated Earnings (Fair Disclosure)",
    "매출액또는손익구조30%(대규모법인은15%)이상변경": "Revenue/P&L Change ≥30% (≥15% for large companies)",
    "매출액또는손익구조30%(대규모법인은15%)이상변동": "Revenue/P&L Change ≥30% (≥15% for large companies)",
    "현금ㆍ현물배당결정": "Cash/In-Kind Dividend Decision",
    "현금·현물배당결정": "Cash/In-Kind Dividend Decision",
    "분기ㆍ중간배당결정": "Quarterly/Interim Dividend Decision",
    "주식배당결정": "Stock Dividend Decision",
    "유상증자결정": "Paid-in Capital Increase (Rights Offering / Placement) Decision",
    "무상증자결정": "Bonus Issue (Free Capital Increase) Decision",
    "유무상증자결정": "Combined Paid-in & Bonus Capital Increase Decision",
    "감자결정": "Capital Reduction Decision",
    "전환사채권발행결정": "Convertible Bond (CB) Issuance Decision",
    "신주인수권부사채권발행결정": "Bond with Warrants (BW) Issuance Decision",
    "교환사채권발행결정": "Exchangeable Bond (EB) Issuance Decision",
    "자기주식취득결정": "Treasury Stock Buyback Decision",
    "자기주식처분결정": "Treasury Stock Disposal Decision",
    "자기주식소각결정": "Treasury Stock Cancellation Decision",
    "주식소각결정": "Share Cancellation Decision",
    "자기주식취득신탁계약체결결정": "Treasury Stock Trust Contract Decision",
    "자기주식취득신탁계약해지결정": "Treasury Stock Trust Contract Termination",
    "자기주식취득결과보고서": "Treasury Stock Buyback Results Report",
    "타법인주식및출자증권취득결정": "Acquisition of Shares in Another Company",
    "타법인주식및출자증권처분결정": "Disposal of Shares in Another Company",
    "유형자산취득결정": "Acquisition of Tangible Assets",
    "유형자산처분결정": "Disposal of Tangible Assets",
    "영업양수결정": "Business Acquisition Decision",
    "영업양도결정": "Business Transfer (Sale) Decision",
    "회사합병결정": "Merger Decision",
    "회사분할결정": "Spin-off / Demerger Decision",
    "회사분할합병결정": "Split-Merger Decision",
    "주식교환ㆍ이전결정": "Share Exchange / Transfer Decision",
    "단일판매ㆍ공급계약체결": "Single Large Sales/Supply Contract",
    "단일판매·공급계약체결": "Single Large Sales/Supply Contract",
    "단일판매ㆍ공급계약해지": "Termination of Large Sales/Supply Contract",
    "신규시설투자등": "New Facility Investment",
    "타인에대한채무보증결정": "Debt Guarantee for Another Party",
    "소송등의제기ㆍ신청": "Litigation Filed",
    "소송등의제기·신청": "Litigation Filed",
    "소송등의판결ㆍ결정": "Litigation Ruling",
    "부도발생": "Default (Dishonored Bill)",
    "영업정지": "Business Suspension",
    "회생절차개시신청": "Filing for Corporate Rehabilitation (Bankruptcy Protection)",
    "해산사유발생": "Cause for Dissolution",
    "기업설명회(IR)개최": "Investor Relations (IR) Event",
    "조회공시요구": "Exchange Inquiry Request",
    "풍문또는보도에대한해명": "Clarification of Rumor / Media Report",
    "불성실공시법인지정": "Designated as Unfaithful Disclosure Company",
    "주권매매거래정지": "Trading Halt",
    "주권매매거래정지해제": "Trading Halt Lifted",
    "관리종목지정": "Designated as Administrative Issue (delisting risk)",
    "상장폐지": "Delisting",
    "주주총회소집결의": "Resolution to Convene Shareholders' Meeting",
    "주주총회소집공고": "Notice of Shareholders' Meeting",
    "정기주주총회결과": "Annual General Meeting Results",
    "임시주주총회결과": "Extraordinary General Meeting Results",
    "대표이사변경": "Change of CEO",
    "사외이사의선임ㆍ해임또는중도퇴임에관한신고": "Outside Director Appointment/Resignation",
    "특수관계인과의내부거래": "Related-Party Transaction",
    "특수관계인에대한증여": "Gift to Related Party",
    "대규모기업집단현황공시": "Large Business Group Status Disclosure",
    "기업가치제고계획": "Corporate Value-up Plan",
    "지속가능경영보고서": "Sustainability Report",
    "주식명의개서정지": "Shareholder Register Closure",
    "기타시장안내": "Other Market Notice",
    "수시공시의무관련사항(공정공시)": "Ad-hoc Disclosure (Fair Disclosure)",
    "장래사업ㆍ경영계획(공정공시)": "Future Business Plan (Fair Disclosure)",
    "투자판단관련주요경영사항": "Material Management Matter for Investment Decisions",
}

TITLE_PREFIXES = {
    "기재정정": "Amended",
    "첨부정정": "Attachment amended",
    "첨부추가": "Attachment added",
    "변경등록": "Registration changed",
    "연장결정": "Extension",
    "발행조건확정": "Issuance terms finalized",
    "정정명령부과": "Correction ordered by FSS",
    "정정제출요구": "Correction requested by FSS",
}

_TITLE_KEYS = sorted(REPORT_TITLES, key=len, reverse=True)
_PREFIX_RE = re.compile(r"^\s*\[([^\]]+)\]\s*")
_PERIOD_RE = re.compile(r"\((\d{4})\.(\d{2})\)")


def translate_report_name(report_nm: str) -> str | None:
    """Best-effort English title for a DART filing name. None if unknown."""
    rest = report_nm
    tags: list[str] = []
    while m := _PREFIX_RE.match(rest):
        tag = m.group(1).replace(" ", "")
        tags.append(TITLE_PREFIXES.get(tag, tag))
        rest = rest[m.end() :]

    compact = rest.replace(" ", "")
    title = next((REPORT_TITLES[k] for k in _TITLE_KEYS if k in compact), None)
    if title is None:
        return None
    if (period := _PERIOD_RE.search(compact)) is not None:
        title += f" (period ending {period.group(1)}-{period.group(2)})"
    if "자율공시" in compact:
        title += " [voluntary]"
    if tags:
        title = f"[{', '.join(tags)}] {title}"
    return title


# --- Accounts --------------------------------------------------------------

ACCOUNT_NAMES: dict[str, str] = {
    "매출액": "Revenue",
    "수익(매출액)": "Revenue",
    "영업수익": "Operating revenue",
    "매출원가": "Cost of sales",
    "매출총이익": "Gross profit",
    "판매비와관리비": "SG&A expenses",
    "영업이익": "Operating profit",
    "영업이익(손실)": "Operating profit (loss)",
    "법인세비용차감전순이익": "Profit before tax",
    "법인세비용차감전순이익(손실)": "Profit (loss) before tax",
    "법인세비용": "Income tax expense",
    "당기순이익": "Net income",
    "당기순이익(손실)": "Net income (loss)",
    "지배기업의소유주에게귀속되는당기순이익": "Net income attributable to owners of parent",
    "비지배지분에귀속되는당기순이익": "Net income attributable to non-controlling interests",
    "기본주당이익": "Basic EPS",
    "희석주당이익": "Diluted EPS",
    "총포괄손익": "Total comprehensive income",
    "자산총계": "Total assets",
    "유동자산": "Current assets",
    "비유동자산": "Non-current assets",
    "현금및현금성자산": "Cash and cash equivalents",
    "단기금융상품": "Short-term financial instruments",
    "매출채권": "Trade receivables",
    "재고자산": "Inventories",
    "유형자산": "Property, plant and equipment",
    "무형자산": "Intangible assets",
    "투자부동산": "Investment property",
    "부채총계": "Total liabilities",
    "유동부채": "Current liabilities",
    "비유동부채": "Non-current liabilities",
    "단기차입금": "Short-term borrowings",
    "장기차입금": "Long-term borrowings",
    "사채": "Bonds (debentures)",
    "매입채무": "Trade payables",
    "자본총계": "Total equity",
    "자본금": "Share capital",
    "자본잉여금": "Capital surplus",
    "이익잉여금": "Retained earnings",
    "이익잉여금(결손금)": "Retained earnings (deficit)",
    "비지배지분": "Non-controlling interests",
    "지배기업의소유주에게귀속되는자본": "Equity attributable to owners of parent",
    "영업활동현금흐름": "Cash flow from operating activities",
    "영업활동으로인한현금흐름": "Cash flow from operating activities",
    "투자활동현금흐름": "Cash flow from investing activities",
    "투자활동으로인한현금흐름": "Cash flow from investing activities",
    "재무활동현금흐름": "Cash flow from financing activities",
    "재무활동으로인한현금흐름": "Cash flow from financing activities",
    "감가상각비": "Depreciation",
    "이자비용": "Interest expense",
    "금융수익": "Finance income",
    "금융비용": "Finance costs",
    "기타수익": "Other income",
    "기타비용": "Other expenses",
    "지분법이익": "Share of profit of associates",
}

_ID_PREFIX_RE = re.compile(r"^(ifrs-full|ifrs|dart|k-ifrs)_", re.IGNORECASE)
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def account_label(account_id: str | None, account_nm: str) -> str | None:
    """English label for a financial statement line.

    Prefers the Korean-name glossary; falls back to humanizing the IFRS/DART
    XBRL taxonomy id (e.g. ifrs-full_ProfitLossAttributableToOwnersOfParent).
    Company-specific ids (entity..._udf_...) can't be translated.
    """
    key = (account_nm or "").replace(" ", "")
    if key in ACCOUNT_NAMES:
        return ACCOUNT_NAMES[key]
    if account_id and _ID_PREFIX_RE.match(account_id):
        words = _CAMEL_RE.sub(" ", _ID_PREFIX_RE.sub("", account_id))
        return words[:1].upper() + words[1:].lower() if words else None
    return None


# --- Shareholder terms -----------------------------------------------------

RELATIONS = {
    "본인": "Largest shareholder (self)",
    "최대주주": "Largest shareholder",
    "최대주주본인": "Largest shareholder (self)",
    "특수관계인": "Related party",
    "임원": "Executive / director",
    "등기임원": "Registered director",
    "계열회사": "Affiliate",
    "계열사": "Affiliate",
    "친인척": "Relative",
    "배우자": "Spouse",
    "자녀": "Child",
    "부": "Father",
    "모": "Mother",
    "형제": "Sibling",
    "재단": "Foundation",
    "비영리법인": "Non-profit entity",
    "자사주": "Treasury stock",
    "우리사주조합": "Employee stock ownership association",
}

STOCK_KINDS = {
    "보통주": "Common",
    "우선주": "Preferred",
    "의결권있는주식": "Voting shares",
    "의결권없는주식": "Non-voting shares",
}

BLOCK_REPORT_TYPES = {
    "일반": "General (active investment purpose)",
    "약식": "Short-form (passive / simple investment)",
    "특례": "Special (institutional investor)",
}

_ALL_TERMS: dict[str, str] = {
    **REPORT_TITLES,
    **ACCOUNT_NAMES,
    **RELATIONS,
    **STOCK_KINDS,
    **{k: v for k, v in TITLE_PREFIXES.items()},
    "공시": "Disclosure / filing",
    "유상증자": "Paid-in capital increase (rights offering / placement; new shares for cash)",
    "무상증자": "Bonus issue (free capital increase)",
    "감자": "Capital reduction",
    "전환사채": "Convertible bond (CB)",
    "신주인수권부사채": "Bond with warrants (BW)",
    "교환사채": "Exchangeable bond (EB)",
    "자기주식": "Treasury stock",
    "자사주매입": "Share buyback",
    "자기주식소각": "Treasury stock cancellation",
    "합병": "Merger",
    "물적분할": "Physical spin-off (parent keeps 100% of the new company)",
    "인적분할": "Pro-rata spin-off (shareholders receive shares of the new company)",
    "대량보유": "Large shareholding (5% rule)",
    "5%룰": "5% rule (block holding disclosure, like 13D/13G)",
    "기업가치제고": "Corporate value-up (Korea's 2024 governance program)",
    "밸류업": "Value-up (Korea's 2024 governance program)",
    "코리아디스카운트": "Korea discount (valuation gap vs. global peers)",
    "최대주주": "Largest shareholder",
    "주요주주": "Major shareholder (10%+ or de facto control)",
    "소액주주": "Minority shareholders",
    "지배주주": "Controlling shareholder",
    "순환출자": "Circular shareholding (chaebol cross-ownership)",
    "일감몰아주기": "Tunneling via related-party contracts",
    "상장폐지": "Delisting",
    "관리종목": "Administrative issue (delisting watch list)",
    "투자주의환기종목": "Investment caution issue",
    "공매도": "Short selling",
    "정정": "Amendment / correction",
    "공정공시": "Fair disclosure",
    "자율공시": "Voluntary disclosure",
    "연결": "Consolidated",
    "별도": "Separate (parent-only)",
    "개별": "Separate (parent-only)",
    "당기": "Current period",
    "전기": "Prior period",
    "전전기": "Two periods prior",
    "제": "Fiscal period number (e.g. 제 56 기 = 56th fiscal period)",
    "결산월": "Fiscal year-end month",
    "대표이사": "CEO / representative director",
    "사외이사": "Outside (independent) director",
    "감사위원회": "Audit committee",
    "지주회사": "Holding company",
    "재벌": "Chaebol (family-controlled conglomerate)",
    "대규모기업집단": "Large business group (chaebol, as designated by FTC)",
    "보호예수": "Lock-up",
    "제3자배정": "Third-party allotment (private placement)",
    "주주배정": "Shareholder allotment (rights offering)",
    "일반공모": "General public offering",
    "리픽싱": "Refixing (conversion price reset)",
    "전환가액": "Conversion price",
    "행사가액": "Exercise price",
    "콜옵션": "Call option",
    "풋옵션": "Put option",
    "백만원": "Million KRW",
    "천원": "Thousand KRW",
    "억원": "100 million KRW",
    "조원": "Trillion KRW",
}


def lookup_terms(terms: list[str]) -> dict[str, str | None]:
    """Look up Korean terms; tries exact, then whitespace-insensitive, then title parsing."""
    compact = {k.replace(" ", ""): v for k, v in _ALL_TERMS.items()}
    out: dict[str, str | None] = {}
    for term in terms:
        key = term.strip()
        out[term] = _ALL_TERMS.get(key) or compact.get(key.replace(" ", "")) or translate_report_name(key)
    return out
