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


def company_profile(details_url: str, *, name: str = "", code: str = "") -> dict[str, str]:
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

    summary = us_summary_zh(description, sector=sector, industry=industry, name=name, code=code)
    return {"ceo": ceo, "industry": industry, "sector": sector, "summary": summary, "sourceUrl": url}


def us_summary_zh(description: str, *, sector: str, industry: str, name: str, code: str) -> str:
    text = " ".join(description.split())
    lower = text.lower()

    if not text:
        return "该公司为美股 IPO 日历中的待上市公司，业务简介请查看来源页。"

    if "blank check" in lower or "acquisition corporation" in lower or "special purpose acquisition" in lower:
        label = f"{name}（{code}）" if name and code else "该公司"
        return f"{label}是一家特殊目的收购公司（SPAC），上市后主要任务是寻找并完成并购标的，本身通常没有实体经营业务。归类在 SPAC 与资本市场板块。"

    if "bw industrial" in lower or "engineering, procurement, and construction" in lower:
        return "BW Industrial 是一家工程、采购与施工服务公司，面向工业客户提供关键工艺系统的设计、建设和集成服务。归类在工业工程与基础设施服务板块。"

    if "riku dining" in lower or "japanese" in lower and "restaurant" in lower:
        return "Riku Dining Group 经营和授权日本主题餐饮品牌，业务覆盖加拿大和香港市场，收入来自门店运营与加盟体系。归类在可选消费与餐饮服务板块。"

    if "conexeu" in lower or "regenerative" in lower or "tissue" in lower:
        return "Conexeu Sciences 聚焦再生医学和组织修复技术，围绕可吸收支架及相关医疗应用推进产品开发。归类在医疗科技与生物材料板块。"

    if "lincoln international" in lower or "investment banking" in lower:
        return "Lincoln International 提供并购、资本市场和企业融资顾问服务，客户包括企业、私募基金和机构投资者。归类在金融服务与投资银行板块。"

    if "software" in lower or "platform" in lower or "cloud" in lower:
        return f"该公司主要提供软件平台或云端服务，业务说明来自美股 IPO 公司资料页。归类在{sector or industry or '软件服务'}板块。"

    if "medical" in lower or "biotechnology" in lower or "pharmaceutical" in lower:
        return f"该公司业务与医疗健康、生命科学或药物研发相关，具体产品线以公司披露资料为准。归类在{sector or industry or '医疗健康'}板块。"

    if "financial" in lower or "bank" in lower or "capital" in lower:
        return f"该公司业务与金融服务、资本市场或企业融资相关，具体收入结构以公司披露资料为准。归类在{sector or industry or '金融服务'}板块。"

    return f"该公司为美股 IPO 日历中的待上市公司，业务简介来自公司资料页；具体主营产品和收入结构建议查看来源链接。归类在{sector or industry or '美股 IPO'}板块。"


def build_us_items() -> list[dict[str, Any]]:
    html = fetch(CALENDAR_URL)
    calendar_items = parse_calendar(html)
    output: list[dict[str, Any]] = []

    for row in calendar_items:
        profile = company_profile(row["detailsUrl"], name=row["name"], code=row["code"])
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
                "marketUrl": "https://www.tradingview.com/",
                "searchCode": row["code"],
                "sourceUrl": profile.get("sourceUrl", row["detailsUrl"]),
                "sourceName": "StockAnalysis IPO Calendar"
            }
        )

    return output


def normalize_float(value: Any) -> str | None:
    text = "" if value is None else str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none", "--"}:
        return None
    return text


def a_share_exchange(code: str) -> str:
    if code.startswith("688") or code.startswith("689"):
        return "上交所科创板"
    if code.startswith("6"):
        return "上交所主板"
    if code.startswith("30"):
        return "深交所创业板"
    if code.startswith(("00", "001", "002")):
        return "深交所主板"
    if code.startswith(("8", "4", "920")):
        return "北交所"
    return "A股"


def eastmoney_symbol(code: str) -> str:
    if code.startswith(("6", "688", "689")):
        return f"SH{code}"
    if code.startswith(("8", "4", "920")):
        return f"BJ{code}"
    return f"SZ{code}"


def a_share_f10_url(code: str) -> str:
    return f"https://emweb.eastmoney.com/PC_HSF10/CompanyManagement/Index?code={eastmoney_symbol(code)}&type=web"


def a_share_market_url(code: str) -> str:
    return "https://www.tradingview.com/"


def a_share_search_code(code: str) -> str:
    if code.startswith(("6", "688", "689")):
        return f"SSE:{code}"
    if code.startswith(("8", "4", "920")):
        return f"BSE:{code}"
    return f"SZSE:{code}"


def fetch_a_share_leader(code: str) -> str:
    try:
        html = fetch(a_share_f10_url(code))
    except Exception:
        return "待补充"

    parser = TextParser()
    parser.feed(html)
    lines = [line.strip() for line in parser.text.splitlines() if line.strip()]
    joined = "\n".join(lines)

    for title in ("董事长", "总经理"):
        pattern = rf"([\u4e00-\u9fa5·]{2,6})\s+[^\n]{{0,40}}{title}"
        match = re.search(pattern, joined)
        if match:
            return f"{title}：{match.group(1)}"

    return "待补充"


def build_a_items() -> list[dict[str, Any]]:
    import akshare as ak  # type: ignore

    df = ak.stock_xgsglb_em(symbol="全部股票")
    today = datetime.now(CN_TZ).date()
    output: list[dict[str, Any]] = []

    for row in df.to_dict(orient="records"):
        code = str(row.get("股票代码", "")).zfill(6)
        name = str(row.get("股票简称", "")).strip()
        listing_raw = row.get("上市日期")
        if not code or not name or listing_raw is None:
            continue

        try:
            listing_date = datetime.fromisoformat(str(listing_raw)[:10]).date()
        except ValueError:
            continue

        days = (listing_date - today).days
        if days < -14 or days > 30:
            continue

        issue_price = normalize_float(row.get("发行价格"))
        current_price = normalize_float(row.get("最新价"))
        exchange = a_share_exchange(code)
        sector = "A股新股"
        if "科创板" in exchange:
            sector = "科创板"
        elif "创业板" in exchange:
            sector = "创业板"
        elif "北交所" in exchange:
            sector = "北交所"

        output.append(
            {
                "id": f"a-{code}",
                "market": "A",
                "code": code,
                "name": name,
                "exchange": exchange,
                "listingDate": listing_date.isoformat(),
                "issuePrice": f"{issue_price} CNY" if issue_price else "待核实",
                "currentPrice": f"{current_price} CNY" if current_price else None,
                "sector": sector,
                "tags": [exchange, "A股", "东方财富新股"],
                "ceo": fetch_a_share_leader(code),
                "summary": f"{name}为东方财富新股数据中的 A 股 IPO 标的，上市日期为{listing_date.isoformat()}，发行价为{issue_price or '待核实'}元。具体主营业务和管理层请查看来源页及公司公告。",
                "marketUrl": a_share_market_url(code),
                "searchCode": a_share_search_code(code),
                "sourceUrl": a_share_f10_url(code),
                "sourceName": "东方财富F10 / 新股数据"
            }
        )

    return output


def merge_items(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for group in groups:
        for item in group:
            if item.get("market") == "A":
                code = str(item.get("code", ""))
                if code:
                    item["searchCode"] = a_share_search_code(code)
                    item["marketUrl"] = a_share_market_url(code)
                    item["sourceUrl"] = a_share_f10_url(code)
                    item["sourceName"] = "东方财富F10 / 新股数据"
                if "待核实" in str(item.get("ceo", "")):
                    item["ceo"] = fetch_a_share_leader(code) if code else "待补充"
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
        a_items = build_a_items()
    except Exception as exc:
        a_items = [item for item in previous.get("items", []) if item.get("market") == "A"]
        notes.append(f"A股自动同步失败，沿用上一版A股数据：{exc}")

    try:
        us_items = build_us_items()
    except Exception as exc:
        us_items = [item for item in previous.get("items", []) if item.get("market") == "US"]
        notes.append(f"美股自动同步失败，沿用上一版美股数据：{exc}")

    items = merge_items(manual.get("items", []), a_items, us_items)
    feed = {
        "updatedAt": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "notes": notes + manual.get("notes", []),
        "items": items
    }
    FEED_PATH.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(items)} IPO records to {FEED_PATH}")


if __name__ == "__main__":
    main()
