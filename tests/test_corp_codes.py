import pytest

from dart_mcp.corp_codes import normalize


def test_normalize_strips_legal_forms():
    assert normalize("SAMSUNG ELECTRONICS CO,.LTD") == normalize("Samsung Electronics") == "samsungelectronics"
    assert normalize("(주)삼성전자") == normalize("삼성전자 주식회사") == "삼성전자"


def test_ticker_and_corp_code(index):
    assert index.search("005930")[0].name_ko == "삼성전자"
    assert index.search("A005930")[0].name_ko == "삼성전자"
    assert index.search("00164779")[0].stock_code == "000660"


def test_english_and_korean_names(index):
    assert index.resolve("Samsung Electronics").corp_code == "00126380"
    assert index.resolve("sk hynix").corp_code == "00164779"
    assert index.resolve("현대모비스").corp_code == "00164788"


def test_listed_ranks_before_unlisted(index):
    results = index.search("samsung")
    assert [c.corp_code for c in results] == ["00126380", "00999999"]
    assert index.search("samsung", listed_only=True)[0].listed


def test_ambiguous_raises_with_candidates(index):
    with pytest.raises(LookupError, match="ambiguous.*Hyundai Motor"):
        index.resolve("hyundai")


def test_no_match(index):
    with pytest.raises(LookupError, match="No DART company"):
        index.resolve("Toyota")
