<!-- mcp-name: io.github.baobabtr33/dart-mcp -->

# Korea DART MCP

**Read Korean corporate filings in English, through Claude or any MCP client.**

[![CI](https://github.com/baobabtr33/dart-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/baobabtr33/dart-mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/korea-dart-mcp)](https://pypi.org/project/korea-dart-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Korea has one of the world's largest stock markets, yet its disclosure system, DART, is
almost entirely in Korean. Samsung's annual report, a KOSDAQ company's convertible bond terms, and
a chaebol's ownership chart are all public, but you can only use them if you read Korean and
know what to look for.

This server gives an AI agent both of those skills. Ask in English:

> *"What has Samsung Electronics disclosed in the last six months, and is anything a red flag?"*

The agent gets back English filing titles, events grouped by type and severity, and
plain-English warnings. Every answer links to the original filing.

The output looks like this (shortened):

```
get_material_events("Samsung Electronics", days=180)
→ counts_by_category: { capital_return, periodic, ownership, earnings, ... }
→ events:   [{ title_en: "Treasury Stock Buyback Decision",
               title_ko: "주요사항보고서(자기주식취득결정)",
               category: "capital_return", severity: "notable",
               why_it_matters: "Shareholder returns: buybacks, cancellations, dividends, or a Value-up plan.",
               url: "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=…" }, …]
→ red_flags: []
```

## Why this one

Several DART MCP servers already exist, and most are built for Korean speakers: Korean
docs, Korean output, one tool per API endpoint. This one is built for people who **don't**
read Korean.

| | Typical DART wrapper | **Korea DART MCP** |
|---|---|---|
| Find a company | By Korean name or the 8-digit `corp_code` | English name, Korean name or ticker (`Samsung Electronics`, `삼성전자` and `005930` all work) |
| Filing titles | `[기재정정]주요사항보고서(전환사채권발행결정)` | Adds `[Amended] Convertible Bond (CB) Issuance Decision` |
| Financials | Raw strings with Korean account names | Integer KRW, English account labels, plus margins, growth, ROE and leverage |
| "Anything I should worry about?" | You read every filing | `get_material_events`: 13 categories, severity levels and red-flag rules for Korea |
| Reading a 300-page annual report | Download a ZIP | `section="business"`, `"mdna"` or `"risk_factors"` jumps to the part you need |
| Context | None | US comparisons (13D, Form 4, 10-K) and a primer on chaebol, KOSDAQ and Value-up |
| Translation | Up to the LLM, sometimes wrong | A curated glossary for jargon. Korean is always returned too, so the model can verify |

## Tools

| Tool | Ask it… |
|---|---|
| `get_material_events` | "What's going on at this company? Any red flags?" or "Which KOSDAQ companies issued convertible bonds this month?" |
| `get_financial_statements` | Balance sheet, income statement and cash flow with English labels and `key_metrics` |
| `compare_companies` | Revenue, margins, ROE and leverage for up to 10 companies side by side |
| `get_filing_text` | Read any filing by section (`business`, `mdna`, `risk_factors`, `audit`, ...), by keyword, or page by page |
| `get_recent_filings` | Filings for a company or the whole market, with English titles. Ranges longer than 90 days are split automatically |
| `get_insider_trades` | Korea's Form 4: each insider's holdings and share changes, with totals for directors and 10%+ holders |
| `get_major_shareholder_changes` | Korea's 13D/13G: who crossed or changed a 5% stake |
| `get_largest_shareholders` | Controlling shareholder and related parties, i.e. the chaebol control structure |
| `get_dividends` | Dividend per share, payout ratio and yield |
| `get_company_profile` | CEO, market, industry, fiscal year-end, IR site |
| `search_company` | Which "Samsung"? Shows the candidates, listed companies first |
| `translate_terms` | Glossary for DART jargon (유상증자, 최대주주, 리픽싱 ...), no API call needed |

It also has a **`company_brief` prompt**, which builds a full English brief from these tools,
and a **`dart://guide/korea-primer` resource** that explains Korean disclosure rules and
common pitfalls.

All tools are marked read-only, so clients can approve them automatically.

## Quick start

**1. Get a free DART API key** (2 minutes, 20,000 requests/day). The OpenDART site is in
Korean, so follow the [English walkthrough](docs/GET_API_KEY.md).

**2. Add it to your client.**

Claude Code:

```bash
claude mcp add dart -e DART_API_KEY=your_key -- uvx korea-dart-mcp
```

Claude Desktop, Cursor, Windsurf and other MCP clients:

```json
{
  "mcpServers": {
    "dart": {
      "command": "uvx",
      "args": ["korea-dart-mcp"],
      "env": { "DART_API_KEY": "your_key" }
    }
  }
}
```

`uvx` comes with [uv](https://docs.astral.sh/uv/getting-started/installation/). To run it
from source instead, use `"command": "uv", "args": ["--directory", "/path/to/dart-mcp", "run", "korea-dart-mcp"]`.

**3. Ask a question.**

- "Write an English investment brief on Samsung Electronics." (or use the `company_brief` prompt)
- "Compare Samsung Electronics and SK hynix on margins and ROE for 2024."
- "Who controls Samsung Electronics? Show the largest shareholder and related parties."
- "How many shares did Samsung Electronics directors and major shareholders add or dispose of this year?"
- "Summarize the business section of Samsung Electronics' latest annual report in English."
- "Which KOSDAQ companies announced convertible bond issues in the last 30 days?"

## Remote / team deployment

```bash
docker build -t korea-dart-mcp .
docker run -e DART_API_KEY=your_key -p 8000:8000 -v dart-cache:/data korea-dart-mcp
# serves MCP over streamable HTTP at http://localhost:8000/mcp
```

The HTTP transport has no authentication. Put it behind a gateway that handles auth before
exposing it.

| Env var | Default | Purpose |
|---|---|---|
| `DART_API_KEY` | (required) | OpenDART key |
| `DART_MCP_CACHE_DIR` | `~/.cache/dart_mcp` | Company list cache (about 100k entities, refreshed weekly) |
| `DART_MCP_LOG_LEVEL` | `INFO` | Logs go to stderr |
| `DART_MCP_HOST` / `DART_MCP_PORT` | `127.0.0.1` / `8000` | HTTP bind address |

## How it works

- **Company resolution:** DART's full company list (about 100k entities, with English names
  where registered) is cached locally and matched by ticker, English name or Korean name.
  Legal-form suffixes like "Co., Ltd." and "(주)" are ignored.
- **Glossary** (`glossary.py`): hand-curated mappings for 80+ filing types, financial
  accounts, ownership relationships and governance terms. Accounts outside the glossary fall
  back to their IFRS XBRL tag (`ifrs-full_ProfitLossAttributableToOwnersOfParent` becomes
  "Profit loss attributable to owners of parent").
- **Diagnostics** (`analysis.py`): rules that classify filings into categories such as
  distress, control change, dilution and exchange scrutiny. On top of that are red-flag
  rules for Korean market patterns, like serial CB issuance, conversion-price refixing and
  frequent amendments. Every rule is plain code with unit tests, and none of it is a black box.
- **Production details:** retries with backoff, a TTL cache, a concurrency limit, DART
  status codes turned into clear errors, EUC-KR fallback, and paging for large filings.

## Limitations

- Structured financials (XBRL) start in FY2015. Some financial firms and unlisted companies
  don't file XBRL, so read their reports with `get_filing_text`.
- Insider "changes" include grants, option exercises and inheritance, not only open-market trades.
- Red flags are heuristics to start an investigation, not investment advice.
- The glossary covers common terms. Unknown terms come back with `*_en: null`, and the LLM
  translates them from the Korean, which is always included.

## Development

```bash
uv sync
uv run pytest            # offline: DART is mocked
uv run ruff check src tests && uv run ruff format --check src tests
```

Contributions are welcome, especially new glossary terms and red-flag rules. See [CLAUDE.md](CLAUDE.md)
for the architecture and conventions.

## License

[MIT](LICENSE). Free to use, modify and redistribute, including commercially, as long as the
copyright notice is kept. DART data belongs to the Financial Supervisory Service
(금융감독원); follow OpenDART's terms of use. Nothing here is investment advice.
