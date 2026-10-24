"""Convert DART original filing documents (zipped DSD/XML markup) to readable text."""

from __future__ import annotations

import html
import io
import re
import zipfile
from dataclasses import dataclass

_TITLE_RE = re.compile(r"<TITLE[^>]*>(.*?)</TITLE>", re.IGNORECASE | re.DOTALL)
_CELL_END_RE = re.compile(r"</(TD|TH|TE|TU)>", re.IGNORECASE)
_BLOCK_RE = re.compile(r"</?(TR|P|BR|SECTION-\d|PGBRK|TABLE|LIBRARY|COVER)[^>]*>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_SPACES_RE = re.compile(r"[ \t 　]+")
_BLANKS_RE = re.compile(r"\n\s*\n+")


@dataclass
class FilingDocument:
    rcept_no: str
    files: list[str]
    text: str
    toc: list[dict[str, object]]


def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "euc-kr", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def markup_to_text(markup: str) -> str:
    """Flatten DART markup: section titles become '## ' headings, table cells ' | '."""
    s = _TITLE_RE.sub(lambda m: "\n\n## " + _TAG_RE.sub("", m.group(1)).strip() + "\n", markup)
    s = _CELL_END_RE.sub(" | ", s)
    s = _BLOCK_RE.sub("\n", s)
    s = _TAG_RE.sub("", s)
    s = html.unescape(s)
    s = _SPACES_RE.sub(" ", s)
    lines = [line.strip().rstrip("|").strip() for line in s.split("\n")]
    return _BLANKS_RE.sub("\n\n", "\n".join(lines)).strip()


def build_toc(text: str) -> list[dict[str, object]]:
    toc: list[dict[str, object]] = []
    offset = 0
    for line in text.split("\n"):
        if line.startswith("## "):
            toc.append({"title": line[3:], "offset": offset})
        offset += len(line) + 1
    return toc


def parse_document_zip(rcept_no: str, blob: bytes) -> FilingDocument:
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        # The main filing is named <rcept_no>.xml; attachments get suffixes.
        names = sorted(
            (n for n in zf.namelist() if n.lower().endswith((".xml", ".html", ".htm"))),
            key=lambda n: (not n.startswith(rcept_no + "."), n),
        )
        parts = []
        for name in names:
            body = markup_to_text(_decode(zf.read(name)))
            if body:
                parts.append(body if name.startswith(rcept_no + ".") else f"\n\n# Attachment: {name}\n\n{body}")
    text = "\n".join(parts)
    return FilingDocument(rcept_no=rcept_no, files=names, text=text, toc=build_toc(text))


def find_snippets(text: str, keyword: str, *, radius: int = 300, limit: int = 10) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    start = 0
    while len(out) < limit:
        idx = text.find(keyword, start)
        if idx == -1:
            break
        lo, hi = max(0, idx - radius), min(len(text), idx + len(keyword) + radius)
        out.append({"offset": idx, "snippet": text[lo:hi]})
        start = hi
    return out


# English section names an analyst would ask for, mapped to Korean heading keywords
# used in DART annual/quarterly reports and registration statements.
SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "overview": ("회사의 개요",),
    "business": ("사업의 내용",),
    "products": ("주요 제품", "주요제품"),
    "risk_factors": ("투자위험요소", "위험요소", "위험관리"),
    "mdna": ("경영진단", "분석의견"),
    "financials": ("재무에 관한 사항",),
    "notes": ("연결재무제표 주석", "재무제표 주석", "주석"),
    "dividends": ("배당에 관한 사항",),
    "audit": ("감사인의 감사의견", "감사의견"),
    "board": ("이사회", "회사의 기관"),
    "shareholders": ("주주에 관한 사항",),
    "executives": ("임원 및 직원", "임원의 현황"),
    "compensation": ("보수",),
    "affiliates": ("계열회사",),
    "related_party": ("대주주 등과의 거래", "특수관계인"),
    "litigation": ("우발부채", "소송"),
    "investor_protection": ("투자자 보호",),
}

_ROMAN_RE = re.compile(r"^[IVX]+\.\s")


def extract_section(doc: FilingDocument, section: str) -> tuple[str, str] | None:
    """Return (heading, text) for an English alias or a Korean heading keyword."""
    keywords = SECTION_ALIASES.get(section.lower().strip(), (section,))
    for keyword in keywords:
        compact = keyword.replace(" ", "")
        for i, entry in enumerate(doc.toc):
            title = str(entry["title"])
            if compact not in title.replace(" ", ""):
                continue
            start = int(entry["offset"])
            top_level = bool(_ROMAN_RE.match(title))
            end = len(doc.text)
            for later in doc.toc[i + 1 :]:
                if not top_level or _ROMAN_RE.match(str(later["title"])):
                    end = int(later["offset"])
                    break
            return title, doc.text[start:end]
    return None
