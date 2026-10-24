import io
import zipfile

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from dart_mcp import server
from dart_mcp.client import DartClient, DartError


def test_parse_amount():
    assert server.parse_amount("1,234,567") == 1234567
    assert server.parse_amount("-1,234") == -1234
    assert server.parse_amount("(500)") == -500
    assert server.parse_amount("12.5") == 12.5
    assert server.parse_amount("-") is None
    assert server.parse_amount("") is None


async def test_recent_filings_translates_titles(mock_dart):
    seen = mock_dart(
        {
            "list.json": {
                "status": "000",
                "page_no": 1,
                "total_count": 1,
                "total_page": 1,
                "list": [
                    {
                        "corp_cls": "Y",
                        "corp_name": "삼성전자",
                        "corp_code": "00126380",
                        "stock_code": "005930",
                        "report_nm": "[기재정정]사업보고서 (2023.12)",
                        "rcept_no": "20240312000736",
                        "flr_nm": "삼성전자",
                        "rcept_dt": "20240312",
                        "rm": "유연",
                    }
                ],
            }
        }
    )
    out = await server.get_recent_filings("Samsung Electronics", filing_type="periodic", start_date="2024-01-01")
    params = seen[0].url.params
    assert params["corp_code"] == "00126380"
    assert params["pblntf_ty"] == "A"
    assert params["bgn_de"] == "20240101"
    assert params["crtfc_key"] == "test-key"
    f = out["filings"][0]
    assert f["title_en"] == "[Amended] Annual Report (period ending 2023-12)"
    assert f["market"] == "KOSPI (main board)"
    assert f["flags"] == ["KOSPI market division filing", "Includes consolidated data"]
    assert f["url"].endswith("20240312000736")


async def test_financials_fall_back_to_separate(mock_dart):
    rows = [
        {
            "rcept_no": "20240312000736",
            "fs_div": "OFS",
            "sj_div": "IS",
            "sj_nm": "손익계산서",
            "account_nm": "매출액",
            "thstrm_nm": "제 55 기",
            "thstrm_amount": "170,374,090,000,000",
            "frmtrm_nm": "제 54 기",
            "frmtrm_amount": "211,867,483,000,000",
            "currency": "KRW",
        }
    ]
    mock_dart({"fnlttSinglAcnt.json": {"status": "000", "list": rows}})
    out = await server.get_financial_statements("005930", 2023)
    assert out["basis"] == "Separate (parent-only)"
    assert out["basis_fallback"] is True
    line = out["statements"][0]["lines"][0]
    assert line == {
        "account_en": "Revenue",
        "account_ko": "매출액",
        "current": 170374090000000,
        "prior": 211867483000000,
    }


async def test_no_financials_gives_actionable_error(mock_dart):
    mock_dart({})
    with pytest.raises(ToolError, match="get_filing_text"):
        await server.get_financial_statements("005930", 2023, detail="full")


async def test_bad_input_becomes_tool_error(mock_dart):
    mock_dart({})
    with pytest.raises(ToolError, match="2015 onward"):
        await server.get_dividends("005930", 2001)
    with pytest.raises(ToolError, match="14-digit"):
        await server.get_filing_text("123")
    with pytest.raises(ToolError, match="ambiguous"):
        await server.get_company_profile("hyundai")


async def test_filing_text_paging_and_search(mock_dart):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("20240312000736.xml", '<TITLE ATOC="Y">배당</TITLE><P>' + "가" * 3000 + "</P><P>현금배당 361원</P>")
    mock_dart({"document.xml": buf.getvalue()})
    page = await server.get_filing_text("20240312000736", max_chars=1000)
    assert page["toc"] == [{"title": "배당", "offset": 0}]
    assert page["next_offset"] == 1000
    hits = await server.get_filing_text("20240312000736", search="361원")
    assert "현금배당 361원" in hits["matches"][0]["snippet"]


async def test_dart_error_status_raises():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"status": "020", "message": "limit"}))
    client = DartClient("k", transport=transport)
    with pytest.raises(DartError, match="Daily request limit"):
        await client.get_json("list.json")


async def test_retries_on_server_error(monkeypatch):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"status": "000", "list": [1]})

    async def no_sleep(_):
        return None

    monkeypatch.setattr("dart_mcp.client.asyncio.sleep", no_sleep)
    client = DartClient("k", transport=httpx.MockTransport(handler))
    assert (await client.get_json("list.json"))["list"] == [1]
    assert calls["n"] == 2
    # Second call is served from cache.
    await client.get_json("list.json")
    assert calls["n"] == 2


async def test_zip_endpoint_error_is_parsed():
    xml = b"<result><status>010</status><message>bad key</message></result>"
    client = DartClient("k", transport=httpx.MockTransport(lambda r: httpx.Response(200, content=xml)))
    with pytest.raises(DartError, match="Unregistered API key"):
        await client.get_zip("corpCode.xml")
