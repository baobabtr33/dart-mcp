import json
from collections.abc import Callable

import httpx
import pytest

from dart_mcp import server
from dart_mcp.client import DartClient
from dart_mcp.corp_codes import CorpIndex

CORP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<result>
  <list><corp_code>00126380</corp_code><corp_name>삼성전자</corp_name>
    <corp_eng_name>SAMSUNG ELECTRONICS CO,.LTD</corp_eng_name><stock_code>005930</stock_code><modify_date>20240101</modify_date></list>
  <list><corp_code>00164779</corp_code><corp_name>SK하이닉스</corp_name>
    <corp_eng_name>SK hynix Inc.</corp_eng_name><stock_code>000660</stock_code><modify_date>20240101</modify_date></list>
  <list><corp_code>00164742</corp_code><corp_name>현대자동차</corp_name>
    <corp_eng_name>Hyundai Motor Company</corp_eng_name><stock_code>005380</stock_code><modify_date>20240101</modify_date></list>
  <list><corp_code>00164788</corp_code><corp_name>현대모비스</corp_name>
    <corp_eng_name>HYUNDAI MOBIS</corp_eng_name><stock_code>012330</stock_code><modify_date>20240101</modify_date></list>
  <list><corp_code>00999999</corp_code><corp_name>삼성전자서비스</corp_name>
    <corp_eng_name>Samsung Electronics Service</corp_eng_name><stock_code> </stock_code><modify_date>20240101</modify_date></list>
</result>""".encode()


@pytest.fixture
def index() -> CorpIndex:
    return CorpIndex.from_xml(CORP_XML)


Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def mock_dart(monkeypatch, index):
    """Install a fake DART backend. Call with {endpoint: payload-or-callable}."""

    def install(routes: dict[str, object]) -> list[httpx.Request]:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            endpoint = request.url.path.rsplit("/", 1)[-1]
            route = routes.get(endpoint)
            if route is None:
                return httpx.Response(200, json={"status": "013", "message": "no data"})
            if callable(route):
                return route(request)
            if isinstance(route, bytes):
                return httpx.Response(200, content=route)
            return httpx.Response(200, content=json.dumps(route).encode())

        svc = server.Service()
        svc._client = DartClient("test-key", transport=httpx.MockTransport(handler), max_retries=2)
        svc._index = index
        monkeypatch.setattr(server, "service", svc)
        return seen

    return install
