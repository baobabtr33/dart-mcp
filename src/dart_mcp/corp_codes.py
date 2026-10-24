"""Company lookup: maps tickers, Korean names, and English names to DART corp_codes.

DART identifies companies by an 8-digit `corp_code`, not by ticker. The full
mapping (~100k entities) ships as a zipped XML file that we cache on disk.
"""

from __future__ import annotations

import io
import logging
import os
import re
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from .client import DartClient

log = logging.getLogger(__name__)

CACHE_MAX_AGE_SECONDS = 7 * 24 * 3600

# Legal-form words stripped from either end of a name before matching.
_AFFIXES = (
    "주식회사",
    "유한회사",
    "coltd",
    "co",
    "ltd",
    "inc",
    "corporation",
    "corp",
    "company",
    "limited",
    "plc",
)


def normalize(name: str) -> str:
    """Lowercase, drop punctuation/whitespace and legal-form affixes ("(주)", "Co., Ltd.")."""
    s = name.lower()
    for marker in ("㈜", "(주)", "(유)", "（주）"):
        s = s.replace(marker, "")
    s = re.sub(r"[^0-9a-z가-힣]", "", s)
    changed = True
    while changed and s:
        changed = False
        for affix in _AFFIXES:
            if len(s) > len(affix) and s.endswith(affix):
                s, changed = s[: -len(affix)], True
            elif len(s) > len(affix) and s.startswith(affix) and not affix.isascii():
                s, changed = s[len(affix) :], True
    return s


@dataclass(frozen=True)
class Corp:
    corp_code: str
    name_ko: str
    name_en: str
    stock_code: str
    modify_date: str

    @property
    def listed(self) -> bool:
        return bool(self.stock_code)

    def to_dict(self) -> dict[str, object]:
        return {
            "corp_code": self.corp_code,
            "name_ko": self.name_ko,
            "name_en": self.name_en or None,
            "ticker": self.stock_code or None,
            "listed": self.listed,
        }


class CorpIndex:
    def __init__(self, corps: list[Corp]):
        self.corps = corps
        self._by_code = {c.corp_code: c for c in corps}
        self._by_ticker = {c.stock_code: c for c in corps if c.stock_code}
        self._norm = [(normalize(c.name_ko), normalize(c.name_en), c) for c in corps]

    def __len__(self) -> int:
        return len(self.corps)

    @classmethod
    def from_xml(cls, xml_bytes: bytes) -> CorpIndex:
        root = ElementTree.fromstring(xml_bytes)
        corps = [
            Corp(
                corp_code=(el.findtext("corp_code") or "").strip(),
                name_ko=(el.findtext("corp_name") or "").strip(),
                name_en=(el.findtext("corp_eng_name") or "").strip(),
                stock_code=(el.findtext("stock_code") or "").strip(),
                modify_date=(el.findtext("modify_date") or "").strip(),
            )
            for el in root.iter("list")
        ]
        return cls([c for c in corps if c.corp_code])

    def get(self, corp_code: str) -> Corp | None:
        return self._by_code.get(corp_code)

    def search(self, query: str, limit: int = 10, listed_only: bool = False) -> list[Corp]:
        q = query.strip()
        if not q:
            return []
        exact = self._by_code.get(q) or self._by_ticker.get(q.upper().removeprefix("A"))
        if q.isdigit() and exact:
            return [exact]

        nq = normalize(q)
        if not nq:
            return []
        scored: list[tuple[int, int, int, Corp]] = []
        for nko, nen, corp in self._norm:
            if listed_only and not corp.listed:
                continue
            rank = _rank(nq, nko)
            rank_en = _rank(nq, nen)
            best = min(rank, rank_en)
            if best < 99:
                length = len(nko) if rank <= rank_en else len(nen)
                scored.append((best, 0 if corp.listed else 1, length, corp))
        scored.sort(key=lambda t: (t[0], t[1], t[2]))
        results = [t[3] for t in scored[:limit]]
        if exact and exact not in results:
            results.insert(0, exact)
        return results[:limit]

    def resolve(self, query: str) -> Corp:
        """Resolve a ticker / corp_code / name to one company, or raise LookupError."""
        matches = self.search(query, limit=5)
        if not matches:
            raise LookupError(
                f"No DART company matches {query!r}. Try the 6-digit ticker, the Korean name, "
                "or call search_company first."
            )
        top = matches[0]
        nq = normalize(query)
        if (
            query.strip() in (top.corp_code, top.stock_code)
            or nq in (normalize(top.name_ko), normalize(top.name_en))
            or len(matches) == 1
        ):
            return top
        options = "; ".join(
            f"{c.name_en or c.name_ko} ({c.name_ko}, ticker={c.stock_code or '-'}, corp_code={c.corp_code})"
            for c in matches
        )
        raise LookupError(f"{query!r} is ambiguous. Candidates: {options}. Pass a ticker or corp_code.")


def _rank(nq: str, name: str) -> int:
    if not name:
        return 99
    if name == nq:
        return 0
    if name.startswith(nq):
        return 1
    if nq in name:
        return 2
    return 99


def default_cache_dir() -> Path:
    if override := os.environ.get("DART_MCP_CACHE_DIR"):
        return Path(override)
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "dart_mcp"


async def load_corp_index(client: DartClient, cache_dir: Path | None = None) -> CorpIndex:
    cache_dir = cache_dir or default_cache_dir()
    path = cache_dir / "CORPCODE.xml"
    if path.exists() and time.time() - path.stat().st_mtime < CACHE_MAX_AGE_SECONDS:
        return CorpIndex.from_xml(path.read_bytes())

    log.info("Downloading DART corp code list")
    try:
        blob = await client.get_zip("corpCode.xml")
    except Exception:
        if path.exists():
            log.warning("Corp code refresh failed; using stale cache", exc_info=True)
            return CorpIndex.from_xml(path.read_bytes())
        raise
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        xml_bytes = zf.read(zf.namelist()[0])
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(xml_bytes)
    tmp.replace(path)
    return CorpIndex.from_xml(xml_bytes)
