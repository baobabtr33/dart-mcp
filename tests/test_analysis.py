import pytest

from dart_mcp.analysis import classify_filing, insider_summary, is_amendment, key_metrics, red_flags


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        # Real titles seen on DART; routine items must not be flagged as distress or control changes.
        ("최대주주등소유주식변동신고서", ("ownership", "info")),
        ("최대주주변경을수반하는주식담보제공계약체결", ("control_change", "warning")),
        ("최대주주변경을수반하는주식양수도계약체결", ("control_change", "critical")),
        ("소송등의제기ㆍ신청(경영권분쟁소송)", ("control_change", "warning")),
        ("주권매매거래정지해제 (액면병합 주권 변경상장)", ("exchange_scrutiny", "info")),
        ("주권매매거래정지 (주식의 병합, 분할 등 전자등록 변경, 말소)", ("exchange_scrutiny", "info")),
        ("주권매매거래정지 (단일판매공급계약)", ("exchange_scrutiny", "info")),
        ("주권매매거래정지 (상장폐지 사유발생)", ("distress", "critical")),
        ("주권매매거래정지해제 (상장폐지에 따른 정리매매 개시)", ("distress", "critical")),
        ("기타시장안내(관리종목지정우려종목) (시가총액 200억원 미달)", ("distress", "warning")),
        ("횡령ㆍ배임혐의발생", ("distress", "critical")),
        ("불성실공시법인지정예고 (공시번복)", ("exchange_scrutiny", "warning")),
        ("주요사항보고서(자기전환사채매도결정)", ("dilution", "warning")),
        ("증권발행결과(자율공시) (제3자배정 유상증자)", ("dilution", "info")),
        ("유상증자또는주식관련사채등의청약결과(자율공시)", ("dilution", "info")),
        ("주요사항보고서(유형자산양수결정)", ("m_and_a", "notable")),
        ("타인에대한채무보증결정", ("credit", "notable")),
        ("임원ㆍ주요주주특정증권등거래계획보고서", ("ownership", "notable")),
        ("주주명부폐쇄기간또는기준일설정", ("governance", "info")),
        ("풍문또는보도에대한해명(미확정)", ("exchange_scrutiny", "info")),
        ("조회공시요구(풍문또는보도)", ("exchange_scrutiny", "warning")),
    ],
)
def test_classify_real_titles(title, expected):
    assert classify_filing(title)[:2] == expected


def test_classify_dilution_and_distress():
    assert classify_filing("주요사항보고서(전환사채권발행결정)")[:2] == ("dilution", "warning")
    assert classify_filing("주권매매거래정지")[:2] == ("distress", "critical")
    assert classify_filing("최대주주변경")[:2] == ("control_change", "critical")
    assert classify_filing("주요사항보고서(자기주식취득결정)")[0] == "capital_return"
    assert classify_filing("사업보고서 (2024.12)")[0] == "periodic"
    assert classify_filing("알 수 없는 공시") == ("other", "info", None)


def test_is_amendment():
    assert is_amendment("[기재정정]사업보고서")
    assert not is_amendment("사업보고서 (2024.12)")


def _event(category, title="", amended=False, severity="warning"):
    return {"category": category, "title_ko": title, "amended": amended, "severity": severity}


def test_red_flags_serial_cb_and_refixing():
    events = [
        _event("dilution", "전환사채권발행결정"),
        _event("dilution", "전환사채권발행결정"),
        _event("other", "전환가액의조정"),
    ]
    flags = red_flags(events, 180)
    assert any("2 dilutive financings" in f for f in flags)
    assert any("refixing" in f for f in flags)


def test_red_flags_clean_company():
    assert red_flags([_event("periodic", severity="info"), _event("capital_return", severity="notable")], 180) == []


def test_red_flags_ignore_routine_large_cap_activity():
    # Samsung-like year: many amended ownership reports, rumor clarifications, routine halts.
    events = [_event("ownership", amended=True, severity="info") for _ in range(17)]
    events += [_event("exchange_scrutiny", "풍문또는보도에대한해명", severity="info") for _ in range(2)]
    events += [_event("capital_return", severity="notable") for _ in range(20)]
    assert red_flags(events, 365) == []


def test_red_flags_amendments():
    events = [_event("m_and_a", amended=True, severity="notable") for _ in range(3)] + [_event("earnings")]
    assert any("3 of 4 material filings were amended" in f for f in red_flags(events, 90))


def test_red_flags_pledge_is_control_risk_not_change():
    flags = red_flags([_event("control_change", "최대주주변경을수반하는주식담보제공계약체결")], 90)
    assert flags == ["Control risk: pledged shares of the largest shareholder or a control dispute."]


def test_key_metrics():
    lines = [
        {"account_ko": "매출액", "current": 1000, "prior": 800},
        {"account_ko": "영업이익", "current": 150, "prior": 100},
        {"account_ko": "당기순이익", "current": 100, "prior": 70},
        {"account_ko": "부채총계", "current": 500},
        {"account_ko": "자본총계", "current": 1000},
    ]
    m = key_metrics(lines)
    assert m["revenue_growth_pct"] == 25.0
    assert m["operating_margin_pct"] == 15.0
    assert m["net_margin_pct"] == 10.0
    assert m["return_on_equity_pct"] == 10.0
    assert m["debt_to_equity_pct"] == 50.0


def test_key_metrics_missing_revenue():
    m = key_metrics([{"account_ko": "자본총계", "current": 10}])
    assert m == {"total_equity": 10}


def test_insider_summary_buying_cluster():
    reports = [{"insider_ko": n, "shares_change": c} for n, c in [("A", 100), ("B", 50), ("A", 30), ("C", -10)]]
    s = insider_summary(reports)
    assert s["signal"] == "net_buying_cluster"
    assert s["signal_basis"] == "all_insiders"
    assert s["all_insiders"]["net_shares"] == 170
    assert s["all_insiders"]["top_buyers"][0] == {"insider_ko": "A", "shares": 130}


def test_insider_signal_ignores_compensation_noise():
    grants = [
        {
            "insider_ko": f"직원{i}",
            "registered_executive_ko": "비등기임원",
            "major_shareholder_ko": "-",
            "shares_change": 100,
        }
        for i in range(40)
    ]
    director_sells = [
        {
            "insider_ko": "대표",
            "registered_executive_ko": "등기임원",
            "major_shareholder_ko": "-",
            "shares_change": -500,
        }
        for _ in range(3)
    ]
    s = insider_summary(grants + director_sells)
    assert s["all_insiders"]["signal"] == "net_buying_cluster"
    assert s["signal"] == "net_selling_cluster"
    assert s["signal_basis"] == "key_insiders"
    assert any("stock compensation" in n for n in s["notes"])


def test_insider_summary_empty():
    assert insider_summary([])["signal"] == "no_change"
