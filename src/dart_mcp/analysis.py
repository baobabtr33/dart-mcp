"""Deterministic diagnostics on top of raw DART data.

This is where domain knowledge lives: which filings matter, what patterns are
red flags in the Korean market, and which ratios an analyst wants first. Kept
free of I/O so every rule is unit-testable.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

SEVERITY_ORDER = {"info": 0, "notable": 1, "warning": 2, "critical": 3}


@dataclass(frozen=True)
class EventRule:
    category: str
    severity: str
    keywords: tuple[str, ...]
    why_en: str


# First matching rule wins, so more specific rules come first.
EVENT_RULES: tuple[EventRule, ...] = (
    EventRule(
        "distress",
        "critical",
        (
            "부도발생",
            "회생절차",
            "파산",
            "해산사유",
            "영업정지",
            "관리종목지정",
            "상장폐지",
            "감사의견거절",
            "의견거절",
            "주권매매거래정지",
            "불성실공시법인지정",
            "횡령",
            "배임",
            "채무불이행",
        ),
        "Distress or governance failure signal: default, rehabilitation, delisting risk, trading halt, "
        "embezzlement, or a non-clean audit opinion.",
    ),
    EventRule(
        "control_change",
        "critical",
        ("최대주주변경", "최대주주등소유주식변동", "공개매수", "경영권"),
        "Change or contest of control. In Korea the largest shareholder usually runs the company, "
        "so this often means a new controlling owner.",
    ),
    EventRule(
        "dilution",
        "warning",
        (
            "전환사채권발행결정",
            "신주인수권부사채권발행결정",
            "교환사채권발행결정",
            "유상증자결정",
            "유무상증자결정",
            "전환가액의조정",
            "리픽싱",
        ),
        "Dilutive financing. Repeated CB/BW issuance with conversion-price resets (refixing) at small "
        "caps is a well-known red flag in Korea.",
    ),
    EventRule(
        "exchange_scrutiny",
        "warning",
        ("조회공시요구", "풍문또는보도에대한해명", "투자주의", "투자경고", "투자위험", "단기과열"),
        "The exchange is asking questions or has flagged abnormal trading.",
    ),
    EventRule(
        "litigation",
        "warning",
        ("소송등의제기", "소송등의판결", "가처분"),
        "Litigation filed or decided.",
    ),
    EventRule(
        "capital_reduction",
        "warning",
        ("감자결정",),
        "Capital reduction. Without compensation it usually follows losses and wipes out value.",
    ),
    EventRule(
        "m_and_a",
        "notable",
        (
            "회사합병결정",
            "회사분할결정",
            "회사분할합병결정",
            "영업양수",
            "영업양도",
            "타법인주식및출자증권취득",
            "타법인주식및출자증권처분",
            "주식교환",
            "유형자산취득결정",
            "유형자산처분결정",
        ),
        "M&A, spin-off, or major asset transaction. Korean spin-offs have been controversial when "
        "minority shareholders don't receive shares of the new entity.",
    ),
    EventRule(
        "capital_return",
        "notable",
        (
            "자기주식취득",
            "자기주식소각",
            "주식소각결정",
            "현금ㆍ현물배당",
            "현금·현물배당",
            "분기ㆍ중간배당",
            "기업가치제고계획",
        ),
        "Shareholder returns: buybacks, cancellations, dividends, or a Value-up plan.",
    ),
    EventRule(
        "earnings",
        "notable",
        ("영업(잠정)실적", "매출액또는손익구조"),
        "Preliminary earnings or a large swing in revenue/profit.",
    ),
    EventRule(
        "large_contract",
        "notable",
        ("단일판매ㆍ공급계약", "단일판매·공급계약", "신규시설투자"),
        "Large sales contract or capex. Check the contract size relative to annual revenue.",
    ),
    EventRule(
        "governance",
        "info",
        ("대표이사변경", "주주총회", "사외이사", "이사회"),
        "Board, CEO, or shareholder meeting matters.",
    ),
    EventRule(
        "ownership",
        "info",
        ("대량보유상황보고", "소유상황보고", "소유주식변동"),
        "Ownership filing by a 5% holder or insider.",
    ),
    EventRule(
        "periodic",
        "info",
        ("사업보고서", "반기보고서", "분기보고서", "감사보고서"),
        "Periodic or audit report.",
    ),
)

CATEGORIES = tuple(dict.fromkeys(r.category for r in EVENT_RULES)) + ("other",)


def classify_filing(report_nm: str) -> tuple[str, str, str | None]:
    """Return (category, severity, why_en) for a filing title."""
    compact = report_nm.replace(" ", "")
    for rule in EVENT_RULES:
        if any(k in compact for k in rule.keywords):
            return rule.category, rule.severity, rule.why_en
    return "other", "info", None


def is_amendment(report_nm: str) -> bool:
    return "정정" in report_nm.split("]")[0] if report_nm.lstrip().startswith("[") else False


def red_flags(events: list[dict[str, Any]], window_days: int) -> list[str]:
    """Plain-English warnings derived from a company's filings in a time window."""
    counts = Counter(e["category"] for e in events)
    titles = " ".join(e.get("title_ko") or "" for e in events).replace(" ", "")
    flags: list[str] = []
    if counts["distress"]:
        flags.append(f"{counts['distress']} distress filing(s): default, delisting risk, trading halt, or audit issue.")
    if counts["control_change"]:
        flags.append("Control change or tender offer in the window. Check who the new controlling shareholder is.")
    if counts["dilution"] >= 2:
        flags.append(
            f"{counts['dilution']} dilutive financings in {window_days} days. Serial CB/BW issuance often precedes "
            "share price weakness at Korean small caps."
        )
    if "전환가액의조정" in titles or "리픽싱" in titles:
        flags.append("Conversion price reset (refixing) on convertible bonds: dilution grows as the price falls.")
    if counts["exchange_scrutiny"]:
        flags.append("The exchange queried the company or flagged abnormal trading.")
    amendments = sum(1 for e in events if e.get("amended"))
    if amendments >= 3:
        flags.append(f"{amendments} amended filings. Frequent corrections can signal weak disclosure controls.")
    return flags


# --- Financial metrics ------------------------------------------------------

_METRIC_ACCOUNTS: dict[str, tuple[str, ...]] = {
    "revenue": ("매출액", "수익(매출액)", "영업수익", "매출"),
    "operating_profit": ("영업이익", "영업이익(손실)"),
    "net_income": ("당기순이익", "당기순이익(손실)", "연결당기순이익"),
    "total_assets": ("자산총계",),
    "total_liabilities": ("부채총계",),
    "total_equity": ("자본총계",),
}


def extract_accounts(lines: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Pick headline accounts from statement lines (as built by server._fs_row)."""
    found: dict[str, dict[str, Any]] = {}
    for metric, names in _METRIC_ACCOUNTS.items():
        for name in names:
            for line in lines:
                if (line.get("account_ko") or "").replace(" ", "") == name and line.get("current") is not None:
                    found[metric] = line
                    break
            if metric in found:
                break
    return found


def _ratio(num: float | None, den: float | None) -> float | None:
    if num is None or not den:
        return None
    return round(num / den * 100, 2)


def key_metrics(lines: list[dict[str, Any]]) -> dict[str, Any]:
    """Margins, growth, and leverage from headline accounts. Percentages, rounded to 0.01."""
    acc = extract_accounts(lines)

    def cur(m: str) -> float | None:
        return acc[m]["current"] if m in acc else None

    def prior(m: str) -> float | None:
        return acc[m].get("prior") if m in acc else None

    rev, rev_prior = cur("revenue"), prior("revenue")
    out: dict[str, Any] = {
        "revenue": rev,
        "operating_profit": cur("operating_profit"),
        "net_income": cur("net_income"),
        "total_assets": cur("total_assets"),
        "total_equity": cur("total_equity"),
        "revenue_growth_pct": _ratio(rev - rev_prior, abs(rev_prior)) if rev is not None and rev_prior else None,
        "operating_margin_pct": _ratio(cur("operating_profit"), rev),
        "net_margin_pct": _ratio(cur("net_income"), rev),
        "return_on_equity_pct": _ratio(cur("net_income"), cur("total_equity")),
        "debt_to_equity_pct": _ratio(cur("total_liabilities"), cur("total_equity")),
    }
    return {k: v for k, v in out.items() if v is not None}


# --- Insider activity --------------------------------------------------------


def insider_summary(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate executive / major shareholder ownership changes into a net signal."""
    buys = [r for r in reports if (r.get("shares_change") or 0) > 0]
    sells = [r for r in reports if (r.get("shares_change") or 0) < 0]
    bought = sum(r["shares_change"] for r in buys)
    sold = -sum(r["shares_change"] for r in sells)
    if not buys and not sells:
        signal = "no_change"
    elif bought >= 2 * sold and len(buys) >= 3:
        signal = "net_buying_cluster"
    elif sold >= 2 * bought and len(sells) >= 3:
        signal = "net_selling_cluster"
    elif bought > sold:
        signal = "net_buying"
    elif sold > bought:
        signal = "net_selling"
    else:
        signal = "mixed"

    def top(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        per: Counter[str] = Counter()
        for r in rows:
            per[r.get("insider_ko") or "?"] += abs(r["shares_change"])
        return [{"insider_ko": name, "shares": n} for name, n in per.most_common(5)]

    return {
        "signal": signal,
        "buy_reports": len(buys),
        "sell_reports": len(sells),
        "shares_bought": bought,
        "shares_sold": sold,
        "net_shares": bought - sold,
        "distinct_insiders": len({r.get("insider_ko") for r in buys + sells}),
        "top_buyers": top(buys),
        "top_sellers": top(sells),
        "note": "Changes include grants, option exercises and inheritance, not only open-market trades. "
        "Open the filing url to see the reason.",
    }
