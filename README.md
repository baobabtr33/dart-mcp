# dart-mcp

An MCP server that gives AI agents and foreign investors access to **DART**, Korea's
electronic corporate disclosure system and its counterpart to SEC EDGAR.

Most Korean filings exist only in Korean, and DART's API returns Korean labels and terse
codes. This server resolves companies by English name or ticker. It translates filing
titles, account names and governance terms with a curated glossary, so that 유상증자 comes
back as "Paid-in Capital Increase (Rights Offering / Placement)" and not a literal
machine translation. Every response keeps the original Korean beside the English, so the
calling model can check the translation and cite the source.

## Tools

| Tool | What it answers |
|---|---|
| `search_company` | Which entity is "Hyundai"? Searches English name, Korean name, ticker or corp_code |
| `get_company_profile` | CEO, market, industry, fiscal year-end, website |
| `get_recent_filings` | What did the company (or the whole market) file recently? Titles are in English |
| `get_filing_text` | Full filing body with a table of contents, paging and keyword search |
| `get_financial_statements` | XBRL BS / IS / CF with English account labels and integer KRW amounts |
| `get_major_shareholder_changes` | 5% block holdings, Korea's version of 13D/13G |
| `get_insider_trades` | Executive and major-shareholder holdings, Korea's version of Form 4 |
| `get_largest_shareholders` | Controlling shareholder and related parties (chaebol structure) |
| `get_dividends` | DPS, payout ratio, yield |
| `translate_terms` | Glossary lookup for DART jargon, with no API call |

It also has the prompt `company_brief`, which builds an English investment brief from these
tools, and the resource `dart://glossary/filing-types`.

## Setup

1. Get a free API key from [OpenDART](https://opendart.fss.or.kr/uss/umt/EgovMberInsertView.do).
   It allows 20,000 requests a day.
2. Install [uv](https://docs.astral.sh/uv/).

### Claude Code

```bash
claude mcp add dart -e DART_API_KEY=your_key -- uv --directory /path/to/dart-mcp run dart-mcp
```

### Claude Desktop / other MCP clients

```json
{
  "mcpServers": {
    "dart": {
      "command": "uv",
      "args": ["--directory", "/path/to/dart-mcp", "run", "dart-mcp"],
      "env": { "DART_API_KEY": "your_key" }
    }
  }
}
```

### Remote (HTTP)

```bash
DART_API_KEY=your_key uv run dart-mcp --transport streamable-http --host 0.0.0.0 --port 8000
# or
docker build -t dart-mcp . && docker run -e DART_API_KEY=your_key -p 8000:8000 dart-mcp
```

The HTTP transport has no authentication. Put it behind a proxy or gateway that handles
auth before you expose it publicly.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `DART_API_KEY` | (required) | OpenDART key |
| `DART_MCP_CACHE_DIR` | `~/.cache/dart_mcp` | Where the corp code list (about 100k companies) is cached. It refreshes weekly |
| `DART_MCP_LOG_LEVEL` | `INFO` | Log level. Logs go to stderr |
| `DART_MCP_HOST` / `DART_MCP_PORT` | `127.0.0.1` / `8000` | HTTP transport bind address |

## Example questions

- "What did Samsung Electronics disclose in the last two weeks? Anything material?"
- "Compare SK hynix's operating margin for 2023 and 2024."
- "Who controls Hyundai Motor, and has any 5% holder changed position this year?"
- "Find all convertible bond issuances on KOSDAQ this month."
- "Summarize the risk factors section of this annual report in English."

## Limitations

- Structured financials (XBRL) start in 2015. Some financial firms and unlisted companies
  don't file XBRL, so read their reports with `get_filing_text`.
- A market-wide `get_recent_filings` search (no company given) is limited to 3 months by DART.
- The glossary covers common filing types and accounts. Unknown terms come back with
  `*_en: null`, and the calling LLM translates them.

## Development

```bash
uv sync
uv run pytest
uv run ruff check src tests && uv run ruff format --check src tests
```

The tests use a mocked DART backend, so no API key or network is needed.
