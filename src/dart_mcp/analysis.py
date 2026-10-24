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


# First matching rule wins, so specific rules come before broad ones. Keywords were
# tuned against real KOSDAQ/KOSPI filing titles; see tests/test_analysis.py.
_WHY = {
    "distress": "Distress or governance failure: default, rehabilitation, delisting process, embezzlement, "
    "or a non-clean audit opinion.",
    "halt": "Trading halted for a non-routine reason. Check the reason in parentheses.",
    "halt_routine": "Routine trading halt or resumption (share split/consolidation, pending disclosure).",
    "delisting_watch": "The exchange warned about delisting criteria (e.g. market cap or price below threshold).",
    "control_sale": "Agreement that transfers control. In Korea the largest shareholder usually runs the "
    "company, so this means a new controlling owner.",
    "control_change": "Largest shareholder changed or a tender offer was launched.",
    "control_pledge": "The largest shareholder pledged shares as loan collateral; a margin call could change control.",
    "control_fight": "Contest for control: shareholder lawsuits, injunctions, or proxy fight.",
    "dilution": "Dilutive financing. Repeated CB/BW issuance with conversion-price resets (refixing) at "
    "small caps is a well-known red flag in Korea.",
    "cb_resale": "The company is reselling convertible bonds it bought back, which re-creates dilution.",
    "dilution_done": "Result or execution of a share/bond issuance, or a conversion into new shares.",
    "unfaithful": "The exchange has designated (or plans to designate) the company for unfaithful "
    "disclosure, such as reversing or failing to make a disclosure.",
    "scrutiny": "The exchange is asking questions or has flagged abnormal trading.",
    "rumor": "The company responded to a press report or rumor. Routine for large caps; read the answer.",
    "litigation": "Litigation filed or decided.",
    "capital_reduction": "Capital reduction. Without compensation it usually follows losses and wipes out value.",
    "credit": "Guarantee, collateral, or loan to another party, or new borrowing. Loans and guarantees to "
    "related parties can move value away from minority shareholders.",
    "m_and_a": "M&A, spin-off, or major asset transaction. Korean spin-offs have been controversial when "
    "minority shareholders don't receive shares of the new entity.",
    "capital_return": "Shareholder returns: buybacks, cancellations, dividends, or a Value-up plan.",
    "earnings": "Earnings release, preview, or a large swing in revenue/profit.",
    "large_contract": "Large sales contract or capex. Check the contract size relative to annual revenue.",
    "insider_plan": "Pre-announced insider trade (required since 2024 for large trades by insiders).",
    "governance": "Board, CEO, shareholder meeting, record date, or stock option matters.",
    "ownership": "Ownership filing by a 5% holder, insider, or the largest shareholder group.",
    "periodic": "Periodic report, audit report, or securities registration document.",
}


def _rule(category: str, severity: str, why: str, *keywords: str) -> EventRule:
    return EventRule(category, severity, keywords, _WHY[why])


EVENT_RULES: tuple[EventRule, ...] = (
    _rule(
        "distress",
        "critical",
        "distress",
        "정리매매",
        "상장폐지결정",
        "상장폐지사유",
        "감사의견거절",
        "의견거절",
        "대출원리금연체",
        "채무불이행",
        "부도발생",
        "회생절차",
        "파산",
        "해산사유",
        "영업정지",
        "횡령",
        "배임",
    ),
    _rule(
        "exchange_scrutiny",
        "info",
        "halt_routine",
        "거래정지해제",
        "액면병합",
        "액면분할",
        "주식의병합",
        "전자등록변경",
        "변경상장",
        "단일판매공급계약",
    ),
    _rule("distress", "critical", "halt", "주권매매거래정지"),
    _rule("distress", "warning", "delisting_watch", "관리종목", "상장폐지", "상장적격성", "개선계획"),
    _rule("exchange_scrutiny", "info", "unfaithful", "불성실공시법인미지정"),
    _rule("exchange_scrutiny", "warning", "unfaithful", "불성실공시"),
    _rule("control_change", "warning", "control_pledge", "주식담보제공"),
    _rule("control_change", "critical", "control_sale", "최대주주변경을수반하는주식양수도", "경영권변경"),
    _rule("control_change", "warning", "control_fight", "경영권분쟁", "경영권"),
    _rule("ownership", "info", "ownership", "최대주주등소유주식변동"),
    _rule("control_change", "critical", "control_change", "최대주주변경", "공개매수"),
    _rule("dilution", "warning", "cb_resale", "자기전환사채매도", "사채매도결정"),
    _rule(
        "dilution",
        "info",
        "dilution_done",
        "증권발행결과",
        "증권발행실적",
        "최종발행가액",
        "청약결과",
        "전환청구권행사",
        "신주인수권행사",
        "소액공모",
        "만기전취득",
        "만기전사채취득",
        "자기전환사채만기전취득",
    ),
    _rule(
        "dilution",
        "warning",
        "dilution",
        "전환사채권발행결정",
        "신주인수권부사채권발행결정",
        "교환사채권발행결정",
        "유상증자결정",
        "유무상증자결정",
        "전환가액의조정",
        "리픽싱",
        "주식관련사채",
    ),
    _rule(
        "exchange_scrutiny",
        "warning",
        "scrutiny",
        "조회공시요구",
        "투자주의",
        "투자경고",
        "투자위험",
        "단기과열",
    ),
    _rule("exchange_scrutiny", "info", "rumor", "풍문또는보도에대한해명"),
    _rule("litigation", "warning", "litigation", "소송등의제기", "소송등의판결", "가처분"),
    _rule("capital_reduction", "warning", "capital_reduction", "감자결정", "자본감소"),
    _rule("credit", "notable", "credit", "채무보증", "담보제공", "금전대여", "단기차입금증가", "사채발행결정"),
    _rule(
        "m_and_a",
        "notable",
        "m_and_a",
        "합병",
        "분할결정",
        "분할합병",
        "영업양수",
        "영업양도",
        "타법인주식및출자증권",
        "주식교환",
        "유형자산양수",
        "유형자산양도",
        "유형자산취득",
        "유형자산처분",
        "자산양수도",
    ),
    _rule(
        "capital_return",
        "notable",
        "capital_return",
        "자기주식취득",
        "자기주식소각",
        "주식소각결정",
        "배당",
        "기업가치제고계획",
        "신탁계약",
    ),
    _rule("capital_return", "info", "capital_return", "자기주식처분"),
    _rule("earnings", "notable", "earnings", "영업(잠정)실적", "매출액또는손익구조", "결산실적공시예고"),
    _rule("large_contract", "notable", "large_contract", "단일판매ㆍ공급계약", "단일판매·공급계약", "신규시설투자"),
    _rule("ownership", "notable", "insider_plan", "거래계획보고서", "거래계획철회"),
    _rule(
        "governance",
        "info",
        "governance",
        "대표이사변경",
        "주주총회",
        "사외이사",
        "독립이사",
        "이사회",
        "주주명부폐쇄",
        "기준일",
        "의결권대리행사",
        "주식매수선택권",
        "본점소재지",
        "주식병합결정",
        "권리락",
        "정관변경",
    ),
    _rule("ownership", "info", "ownership", "대량보유상황보고", "소유상황보고", "소유주식변동"),
    _rule(
        "periodic",
        "info",
        "periodic",
        "사업보고서",
        "반기보고서",
        "분기보고서",
        "감사보고서",
        "증권신고서",
        "투자설명서",
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
    """Plain-English warnings derived from a company's filings in a time window.

    Only warning/critical events count, so routine items (halts for share splits, rumor
    clarifications, amended ownership reports) don't flag healthy large caps.
    """
    serious = [e for e in events if SEVERITY_ORDER[e["severity"]] >= SEVERITY_ORDER["warning"]]
    counts = Counter(e["category"] for e in serious)
    titles = " ".join(e.get("title_ko") or "" for e in events).replace(" ", "")
    flags: list[str] = []
    if counts["distress"]:
        flags.append(
            f"{counts['distress']} distress filing(s): default, delisting process or warning, non-routine "
            "trading halt, embezzlement, or audit issue."
        )
    critical_control = [e for e in serious if e["category"] == "control_change" and e["severity"] == "critical"]
    if critical_control:
        flags.append("Control change or tender offer in the window. Check who the new controlling shareholder is.")
    elif counts["control_change"]:
        flags.append("Control risk: pledged shares of the largest shareholder or a control dispute.")
    if counts["dilution"] >= 2:
        flags.append(
            f"{counts['dilution']} dilutive financings in {window_days} days. Serial CB/BW issuance often precedes "
            "share price weakness at Korean small caps."
        )
    if "전환가액의조정" in titles or "리픽싱" in titles:
        flags.append("Conversion price reset (refixing) on convertible bonds: dilution grows as the price falls.")
    if counts["exchange_scrutiny"]:
        flags.append("The exchange queried the company, flagged abnormal trading, or cited unfaithful disclosure.")
    material = [e for e in events if e["category"] not in ("ownership", "periodic")]
    amended = sum(1 for e in material if e.get("amended"))
    if amended >= 3 and amended >= 0.25 * len(material):
        flags.append(
            f"{amended} of {len(material)} material filings were amended. Frequent corrections can signal weak "
            "disclosure controls."
        )
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


def is_key_insider(report: dict[str, Any]) -> bool:
    """Registered directors and major (10%+) shareholders: the trades that carry signal.

    Large Korean companies file thousands of reports for non-registered executives receiving
    stock compensation, which would otherwise drown out the signal.
    """
    registered = (report.get("registered_executive_ko") or "").replace(" ", "") == "등기임원"
    major = (report.get("major_shareholder_ko") or "-").strip() not in ("-", "", "해당없음")
    return registered or major


def _flow(rows: list[dict[str, Any]]) -> dict[str, Any]:
    buys = [r for r in rows if (r.get("shares_change") or 0) > 0]
    sells = [r for r in rows if (r.get("shares_change") or 0) < 0]
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

    def top(group: list[dict[str, Any]]) -> list[dict[str, Any]]:
        per: Counter[str] = Counter()
        for r in group:
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
    }


def insider_summary(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Net buy/sell signal, led by registered directors and major shareholders."""
    key = [r for r in reports if is_key_insider(r)]
    everyone = _flow(reports)
    notes = [
        "Changes include grants, option exercises and inheritance, not only open-market trades. "
        "Open the filing url to see the reason."
    ]
    if everyone["distinct_insiders"] >= 30 and len(key) < len(reports) / 5:
        notes.append(
            f"{everyone['distinct_insiders']} insiders filed, mostly non-registered executives. That pattern "
            "usually reflects stock compensation, so rely on key_insiders for the signal."
        )
    return {
        "signal": _flow(key)["signal"] if key else everyone["signal"],
        "signal_basis": "key_insiders" if key else "all_insiders",
        "key_insiders": _flow(key),
        "all_insiders": everyone,
        "notes": notes,
    }
