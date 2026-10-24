# dart-mcp

MCP server that wraps Korea's OpenDART API (https://opendart.fss.or.kr) for
English-speaking agents and investors. Python 3.10+, `mcp` SDK 2.x (`MCPServer`, not the
v1 `FastMCP`), httpx, uv.

## Commands

- `uv sync`: install
- `uv run pytest -q`: tests (offline; DART is mocked with `httpx.MockTransport`)
- `uv run ruff check src tests && uv run ruff format src tests`: lint and format (line length 120)
- `DART_API_KEY=... uv run dart-mcp`: run over stdio. Add `--transport streamable-http` for HTTP.

## Layout

- `src/dart_mcp/server.py`: MCP tools, prompt, resource, CLI entry point. Holds the lazy
  `Service` (client, corp index, document LRU).
- `src/dart_mcp/client.py`: `DartClient` (auth, DART status codes, retries, TTL cache,
  concurrency limit). `DartError` carries the DART status code.
- `src/dart_mcp/corp_codes.py`: downloads and caches `corpCode.xml` (about 100k companies)
  and resolves ticker, corp_code, Korean name or English name to a `Corp`.
- `src/dart_mcp/glossary.py`: curated Korean-to-English mappings for codes, filing titles,
  accounts and governance terms. This is the product's core value.
- `src/dart_mcp/document.py`: turns DART filing ZIPs (DSD/XML markup) into text with a TOC.

## Conventions

- Every tool output keeps the original Korean (`*_ko`) beside the English (`*_en`). Use
  `None` for `*_en` when no translation is known. Never guess a translation in code; the
  calling LLM fills the gaps.
- Every filing reference includes `url` (the DART viewer link) so agents can cite it.
- Amounts are parsed into int/float KRW with `parse_amount`, and dates are formatted as
  `YYYY-MM-DD` with `fmt_date`. DART itself takes `YYYYMMDD`.
- Tools accept `company` as ticker, corp_code or name, resolved via `service.resolve()`.
  An ambiguous name raises `LookupError` with candidate names.
- Wrap tools in `@tool_errors` so that `LookupError`, `ValueError` and `DartError` reach the
  agent as `ToolError` with an actionable message (what to try next).
- stdout is the MCP channel on stdio. Log only through `logging` (stderr), never `print`.
- Status `013` (no data) is not an error: `get_json` returns `list: []`.

## Adding a tool

1. Find the endpoint in the OpenDART docs (https://opendart.fss.or.kr/guide/main.do) and
   note its request params and response fields.
2. Add an `@mcp.tool()` + `@tool_errors` async function in `server.py`. Write the docstring
   for an agent: what the data means in US terms (e.g. "Korea's Form 4") and when to use it.
3. Map coded or Korean fields through `glossary.py`. Add new terms there, not inline.
4. Add a test in `tests/test_server.py` using the `mock_dart` fixture.

## DART API gotchas

- Companies are keyed by the 8-digit `corp_code`, not the ticker. Always resolve first.
- `reprt_code`: 11011 annual, 11012 half, 11013 Q1, 11014 Q3. There is no Q4 report; use annual.
- `fs_div`: CFS consolidated, OFS separate. Companies without subsidiaries only have OFS.
- Quarterly income statements: `thstrm_amount` covers 3 months and `thstrm_add_amount` is year-to-date.
- `list.json` without `corp_code` is limited to a 3-month range.
- ZIP endpoints (`corpCode.xml`, `document.xml`) return XML or JSON error bodies instead of a ZIP on failure.
- Older filings may be EUC-KR encoded.
- The limit is 20,000 requests a day per key (status `020`).
