from dart_mcp.analysis import classify_filing, insider_summary, is_amendment, key_metrics, red_flags


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


def _event(category, title="", amended=False):
    return {"category": category, "title_ko": title, "amended": amended}


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
    assert red_flags([_event("periodic"), _event("capital_return")], 180) == []


def test_red_flags_amendments():
    events = [_event("periodic", amended=True) for _ in range(3)]
    assert any("3 amended filings" in f for f in red_flags(events, 90))


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
    assert s["net_shares"] == 170
    assert s["top_buyers"][0] == {"insider_ko": "A", "shares": 130}


def test_insider_summary_empty():
    assert insider_summary([])["signal"] == "no_change"
