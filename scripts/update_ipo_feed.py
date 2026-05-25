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

ROOT = Path(__file__).resolve().parents[1]
FEED_PATH = ROOT / "data" / "ipo-feed.json"
MANUAL_PATH = ROOT / "data" / "manual-ipo-overrides.json"
CALENDAR_URL = "https://stockanalysis.com/ipos/calendar/"

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
            listing_date = datetime.strptime(cells[0]["text"], "%b %d, %Y").date().isoformat()
        except ValueError:
            continue

        symbol = cells[1]["text"].upper()
        href = cells[1]["href"]
        if not symbol or not href:
            continue

        items.append(
            {
                "listingDate": listing_date,
                "code": symbol,
                "name": cells[2]["text"],
                "exchange": cells[3]["text"],
                "issuePrice": cells[4]["text"].replace("$", "").strip() + " USD",
                "detailsUrl": f"https://stockanalysis.com{href}" if href.startswith("/") else href,
            }
        )

    return items


def company_profile(details_url: str) -> dict[str, str]:
    url = details_url.rstrip("/") + "/company/"
    try:
        html = fetch(url)
    except URLError:
        return {}

    parser = TextParser()
    parser.feed(html)
    text = parser.text

    ceo = "待核实"
    ceo_match = re.search(r"\bCEO\s+(Mr\.|Ms\.|Mrs\.)?\s*([^\n]+)", text)
    if ceo_match:
        ceo = ceo_match.group(0).replace("CEO", "").strip()

    industry = "美股 IPO"
    industry_match = re.search(r"\bIndustry\s+([^\n]+)", text)
    if industry_match:
        industry = industry_match.group(1).strip()

    sector = "美股 IPO"
    sector_match = re.search(r"\bSector\s+([^\n]+)", text)
    if sector_match:
        sector = sector_match.group(1).strip()

    description = ""
    marker = "Company Description\n"
    if marker in text:
        after = text.split(marker, 1)[1]
        description = after.split("\nCountry ", 1)[0].strip()
    if not description:
        description = "该公司为美股 IPO 日历中的待上市公司，业务简介请查看来源页。"

    summary = " ".join(description.split())[:260]
    return {"ceo": ceo, "industry": industry, "sector": sector, "summary": summary, "sourceUrl": url}


def build_us_items() -> list[dict[str, Any]]:
    html = fetch(CALENDAR_URL)
    calendar_items = parse_calendar(html)
    output: list[dict[str, Any]] = []

    for row in calendar_items:
        profile = company_profile(row["detailsUrl"])
        sector = profile.get("sector") or profile.get("industry") or "美股 IPO"
        output.append(
            {
                "id": f"us-{row['code'].lower()}",
                "market": "US",
                "code": row["code"],
                "name": row["name"],
                "exchange": row["exchange"],
                "listingDate": row["listingDate"],
                "issuePrice": row["issuePrice"],
                "currentPrice": None,
                "sector": sector,
                "tags": [profile.get("industry", "IPO"), row["exchange"], "美股"],
                "ceo": profile.get("ceo", "待核实"),
                "summary": profile.get("summary", "该公司为美股 IPO 日历中的待上市公司，业务简介请查看来源页。"),
                "marketUrl": row["detailsUrl"],
                "sourceUrl": profile.get("sourceUrl", row["detailsUrl"]),
                "sourceName": "StockAnalysis IPO Calendar"
            }
        )

    return output


def merge_items(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for group in groups:
        for item in group:
            merged[item["id"]] = item
    return sorted(merged.values(), key=lambda item: (item["listingDate"], item["market"], item["code"]))


def main() -> None:
    manual = read_json(MANUAL_PATH, {"notes": [], "items": []})
    previous = read_json(FEED_PATH, {"items": []})
    notes = [
        "自动更新：美股 IPO 日历由 StockAnalysis 同步；港股/A股暂由 data/manual-ipo-overrides.json 补充。",
        "IPO 日期可能会变化；未上市股票的行情入口优先指向 IPO 详情页，上市后再接实时行情。"
    ]

    try:
        us_items = build_us_items()
    except Exception as exc:
        us_items = [item for item in previous.get("items", []) if item.get("market") == "US"]
        notes.append(f"美股自动同步失败，沿用上一版美股数据：{exc}")

    items = merge_items(manual.get("items", []), us_items)
    feed = {
        "updatedAt": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "notes": notes + manual.get("notes", []),
        "items": items
    }
    FEED_PATH.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(items)} IPO records to {FEED_PATH}")


if __name__ == "__main__":
    main()
