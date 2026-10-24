# Launch kit: Korea DART MCP

## Positioning

**One line:** Read Korean corporate filings in English, through Claude or any MCP client.

**Who it's for**
1. Foreign investors and analysts covering Korea (hedge funds, EM funds, independent
   researchers). They can't read DART today and depend on brokers' English summaries.
2. People building AI agents for finance who need a Korea data source.
3. Journalists and researchers covering Korean companies and chaebol governance.

**Why now**
- Korea's "Corporate Value-up" program has brought foreign attention back to the "Korea
  discount" story.
- DART is free and complete, but it is Korean-only. LLMs can now bridge the language gap,
  if they're given structured data and domain rules instead of raw ZIP files.

**Difference from other DART MCPs:** they are Korean-first API wrappers. This one is
English-first, with a curated glossary, US comparisons (Form 4, 13D, 10-K), red-flag rules
specific to Korea, and a way to jump straight to a report section.

**Proof points to repeat:** `Samsung Electronics`, `삼성전자` and `005930` all resolve to the
same company · 12 read-only tools · 13 event categories with red-flag rules · MIT licensed ·
free DART key.

---

## Pre-launch checklist

- [ ] Test with a real DART key: run every README example question against Samsung Electronics.
- [ ] Record a 30–45 second demo GIF (script below) and add it to the top of the README.
- [ ] Publish to PyPI: `uv build && uv publish` (needs a PyPI token). Then check that
      `uvx korea-dart-mcp` works on a clean machine.
- [ ] Publish to the official MCP Registry: install `mcp-publisher`, run
      `mcp-publisher login github`, then `mcp-publisher publish` (uses `server.json`;
      the `mcp-name` comment in the README proves PyPI ownership).
- [ ] GitHub repo: add description, topics and a social preview image (1280×640, a
      screenshot of the demo).
- [ ] Tag the release `v0.2.0` with short release notes.

## Directories to submit to

| Where | How |
|---|---|
| Official MCP Registry | `mcp-publisher publish` |
| awesome-mcp-servers (punkpeye) | PR under **Finance & Fintech** |
| Smithery | smithery.ai → Add server (connect the GitHub repo) |
| Glama | glama.ai/mcp/servers → Add server |
| PulseMCP | pulsemcp.com → Submit |
| mcp.so | Submit form |
| Cursor directory | cursor.directory → MCP → Submit |

---

## Demo GIF script (Claude Desktop, about 40 seconds)

1. Type: *"Write a short English brief on Samsung Electronics: latest financials, material
   events in the last 6 months, and who controls it."*
2. Show the tool calls appearing: `get_financial_statements` → `get_material_events` →
   `get_largest_shareholders`.
3. Scroll the answer: the metrics table, events with English titles, the control structure,
   and the cited DART links.
4. Click one DART link so the original Korean filing opens, to show the answer is grounded
   in the source.

---

## Show HN

**Title:** Show HN: Read Korean corporate filings in English with an MCP server

**Body:**

Korea's disclosure system, DART, is free and complete: every annual report, insider trade,
5% stake and convertible bond issue. But it's almost entirely in Korean, so most foreign
investors depend on broker summaries.

I built an MCP server that lets Claude (or any MCP client) work with DART in English:

- Find companies by English name, Korean name or ticker
- English filing titles from a curated glossary. Machine translation gets terms like
  유상증자 ("paid-in capital increase", i.e. a rights offering) wrong.
- Financials with English labels plus margins, growth and ROE
- `get_material_events` sorts filings into distress / control change / dilution / etc. and
  flags Korean market patterns such as serial convertible bond issuance with
  conversion-price resets
- Jump to sections of a 300-page annual report ("business", "mdna", "risk_factors")
  instead of downloading ZIPs

It always returns the original Korean next to the English, so the model can check the
translation, and every answer links to the source filing.

Python, MIT licensed, needs a free DART API key. Feedback welcome, especially from anyone
who covers Korean equities: which red flags am I missing?

https://github.com/baobabtr33/dart-mcp

---

## X / Twitter thread

1/ Korea has one of the world's largest stock markets, and almost all of its corporate
filings are in Korean only.

I built an open-source MCP server so Claude can read them for you, in English. 🧵

2/ Ask: "What has Samsung Electronics disclosed in the last 6 months? Any red flags?"

You get English filing titles, events grouped by severity, and links to every source.
[demo GIF]

3/ It's more than translation. It has rules that come from how the Korean market works:
• serial convertible bond issues and conversion-price "refixing"
• control changes in chaebol companies
• exchange inquiries and trading halts
• frequent amended filings

4/ It also maps Korean filings to their US equivalents:
사업보고서 → 10-K
대량보유보고 → 13D/13G
임원ㆍ주요주주 소유보고 → Form 4
…so the model explains them in terms you already know.

5/ MIT licensed, free DART key, one line to install:
claude mcp add dart -e DART_API_KEY=… -- uvx korea-dart-mcp

github.com/baobabtr33/dart-mcp

---

## LinkedIn

Foreign investors hold roughly 30% of KOSPI by market value, yet the primary source, DART,
the Korean equivalent of SEC EDGAR, is almost entirely in Korean.

I built an open-source tool that closes that gap. Korea DART MCP connects Claude and other
AI assistants directly to DART and returns English output:

✅ English filing titles and account names from a curated glossary, not raw machine translation
✅ Financials with margins, growth and ROE
✅ Red-flag detection for Korean market patterns: serial convertible bonds, control
   changes, exchange inquiries
✅ Ownership mapped to US terms (13D, Form 4) and the chaebol control structure
✅ Source links on every answer

Example: "Compare Samsung Electronics and SK hynix on margins and ROE for 2024," answered
from the primary filings in seconds.

Free and MIT licensed. If you cover Korean equities, I'd value your feedback on what to
add next.

github.com/baobabtr33/dart-mcp

#Korea #EmergingMarkets #AI #Investing #ValueUp

---

## Reddit

Good fits: **r/mcp**, **r/ClaudeAI** (as a tool showcase), **r/ValueInvesting** and
**r/EmergingMarkets** (lead with the investing angle, not the code). Read each subreddit's
self-promotion rules first, and post as a genuine "I built this, feedback welcome" rather
than an ad.

**Title (r/ValueInvesting):** I made a free tool that lets Claude read Korean company
filings in English. Korea-discount hunters, what should it flag?

**Body:** Use the Show HN body, but open with the investing problem and move the setup
details to the end.

---

## GeekNews (Korean dev community, news.hada.io)

**Title:** 외국인 투자자를 위한 영어 DART MCP 서버 (Korea DART MCP)

**Body:**

DART 공시를 영어로 읽을 수 있게 해주는 MCP 서버를 만들었습니다. 기존 DART MCP들은 대부분
한국어 사용자를 위한 API 래퍼라서, 외국인 투자자나 영어 기반 AI 에이전트가 쓰기 어려웠습니다.

- 영문명·한글명·종목코드 어느 것으로도 회사 검색 (`Samsung Electronics` = `삼성전자` = `005930`)
- 공시 제목·계정과목을 큐레이션된 용어집으로 영어 변환 (예: 유상증자 → Paid-in Capital
  Increase), 원문 한국어도 항상 함께 반환
- 공시를 위험도별로 분류하고 한국 시장 특유의 레드플래그 탐지 (CB 반복 발행, 리픽싱, 최대주주
  변경, 조회공시 등)
- 사업보고서를 섹션 단위로 읽기 (`business`, `mdna`, `risk_factors` …)
- 미국 공시와 대응 설명 (대량보유보고 ≈ 13D, 임원 소유보고 ≈ Form 4)

Python, MIT 라이선스. 용어집과 레드플래그 규칙에 대한 기여 환영합니다.

https://github.com/baobabtr33/dart-mcp

---

## Follow-up content (weeks 2–6)

Each post should come from a real query and be a useful finding in its own right, with the
tool as the way the finding was made:

1. "What Samsung Electronics' last annual report says, in English, in 5 minutes": a walkthrough.
2. "How to spot a KOSDAQ convertible bond spiral": the red-flag rules explained with real
   (anonymized or public) cases.
3. "Chaebol control structure, explained with primary filings": `get_largest_shareholders` on Samsung Electronics.
4. "Value-up tracker": all 기업가치제고계획 (Value-up plan) filings this quarter, via
   `get_material_events(categories=["capital_return"])`.

## Metrics to watch

GitHub stars, PyPI downloads (pypistats.org), MCP directory views, and issues opened by
non-Korean users. Issues from non-Korean users are the real signal that the positioning works.
