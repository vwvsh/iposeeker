from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
FEED_PATH = ROOT / "data" / "ipo-feed.json"
MANUAL_PATH = ROOT / "data" / "manual-ipo-overrides.json"
CALENDAR_URL = "https://stockanalysis.com/ipos/calendar/"
CN_TZ = ZoneInfo("Asia/Shanghai")
RECENT_LISTED_DAYS = 14
LOOKAHEAD_DAYS = 30

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; IPOSeekerBot/1.0; +https://github.com/vwvsh/iposeeker)"
}


class TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[dict[str, str]]] = []
        self._row: list[dict[str, str]] | None = None
        self._cell: dict[str, str] | None = None
        self._in_cell = False
        self._link = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = {"text": "", "href": ""}
            self._in_cell = True
        elif tag == "a" and self._in_cell:
            href = dict(attrs).get("href") or ""
            if href:
                self._link = href

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell["text"] += data

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._cell["text"] = " ".join(unescape(self._cell["text"]).split())
            self._cell["href"] = self._link
            self._row.append(self._cell)
            self._cell = None
            self._link = ""
            self._in_cell = False
        elif tag == "tr" and self._row:
            self.rows.append(self._row)
            self._row = None


class TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if text:
            self.parts.append(text)

    @property
    def text(self) -> str:
        return "\n".join(self.parts)


def fetch(url: str) -> str:
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=25) as response:
        return response.read().decode("utf-8", errors="replace")


def read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def parse_calendar(html: str) -> list[dict[str, str]]:
    parser = TableParser()
    parser.feed(html)
    items: list[dict[str, str]] = []

    for row in parser.rows:
        cells = [cell for cell in row if cell["text"]]
        if len(cells) < 5 or cells[0]["text"] == "IPO Date":
            continue
        try:
