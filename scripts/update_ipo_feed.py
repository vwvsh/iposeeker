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
                "marketUrl": "https://www.google.com/finance/",
                "searchCode": row["code"],
                "sourceUrl": profile.get("sourceUrl", row["detailsUrl"]),
                "sourceName": "StockAnalysis IPO Calendar"
            }
        )

    return output


def normalize_float(value: Any) -> str | None:
    text = "" if value is None else str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none", "--", "-", "待上市"}:
        return None
    return text


def parse_date(value: Any) -> datetime.date | None:
    text = "" if value is None else str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none", "--", "-"}:
        return None
    for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(text[:10], pattern).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text[:10]).date()
    except ValueError:
        return None


def is_in_feed_window(listing_date: datetime.date, today: datetime.date) -> bool:
    days = (listing_date - today).days
    return -RECENT_LISTED_DAYS <= days <= LOOKAHEAD_DAYS


def is_listed(item: dict[str, Any]) -> bool:
    listing_date = parse_date(item.get("listingDate"))
    return bool(listing_date and listing_date <= datetime.now(CN_TZ).date())


def format_market_price(value: Any, currency: str) -> str | None:
    text = normalize_float(value)
    if not text:
        return None
    try:
        number = float(str(text).replace(",", ""))
    except ValueError:
        return None
    if number <= 0:
        return None
    return f"{number:.2f} {currency}"


def eastmoney_hk_price(code: str) -> str | None:
    url = f"https://push2.eastmoney.com/api/qt/stock/get?secid=116.{code.zfill(5)}&fields=f43,f58"
    try:
        payload = json.loads(fetch(url))
    except Exception:
        return None

    data = payload.get("data") or {}
    raw_price = data.get("f43")
    try:
        price = float(raw_price) / 1000
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    return f"{price:.2f} HKD"


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
    return "https://www.google.com/finance/"


def a_share_search_code(code: str) -> str:
    if code.startswith(("6", "688", "689")):
        return f"{code}:SHA"
    if code.startswith(("8", "4", "920")):
        return f"{code}:BJS"
    return f"{code}:SHE"


def first_value_by_label(records: list[dict[str, Any]], labels: tuple[str, ...]) -> str:
    for record in records:
        items = [(str(key).strip(), str(value).strip()) for key, value in record.items()]
        for key, value in items:
            if not value or value.lower() in {"nan", "none", "--"}:
                continue
            if any(label in key for label in labels):
                return value
            if any(label == value for label in labels):
                for _, other_value in items:
                    if other_value and other_value != value and other_value.lower() not in {"nan", "none", "--"}:
                        return other_value
    return ""


def concise_business_text(text: str, limit: int = 88) -> str:
    cleaned = re.sub(r"\s+", "", text)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip("，。、；;") + "等"


def fetch_a_share_business_summary(code: str, name: str, sector: str) -> str:
    try:
        import akshare as ak  # type: ignore

        df = ak.stock_zyjs_ths(symbol=code)
        records = df.to_dict(orient="records")
    except Exception:
        records = []

    business = first_value_by_label(records, ("主营业务", "主营介绍", "经营范围"))
    product_type = first_value_by_label(records, ("产品类型", "业务类型"))
    product_name = first_value_by_label(records, ("产品名称", "主要产品"))

    if business:
        summary = f"{name}主要从事{concise_business_text(business)}。"
        if product_type and product_type not in business:
            summary += f"主要产品或服务类型包括{concise_business_text(product_type, 44)}。"
        elif product_name and product_name not in business:
            summary += f"主要产品包括{concise_business_text(product_name, 44)}。"
        summary += f"归类在{sector}板块。"
        return summary

    return f"{name}为 A 股 IPO 标的，具体主营业务、产品结构和管理层信息请查看 F10 资料及公司公告。归类在{sector}板块。"


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

        listing_date = parse_date(listing_raw)
        if not listing_date:
            continue

        if not is_in_feed_window(listing_date, today):
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
                "summary": fetch_a_share_business_summary(code, name, sector),
                "marketUrl": a_share_market_url(code),
                "searchCode": a_share_search_code(code),
                "sourceUrl": a_share_f10_url(code),
                "sourceName": "东方财富F10 / 新股数据"
            }
        )

    return output


def hk_search_code(code: str) -> str:
    return f"{code.lstrip('0') or code}:HKG"


def build_h_items() -> list[dict[str, Any]]:
    import akshare as ak  # type: ignore

    df = ak.stock_ipo_hk_ths()
    today = datetime.now(CN_TZ).date()
    output: list[dict[str, Any]] = []

    for row in df.to_dict(orient="records"):
        raw_code = first_value_by_label([row], ("股票代码", "证券代码", "代码"))
        code = re.sub(r"\D", "", raw_code).zfill(5)
        name = (
            first_value_by_label([row], ("股票简称", "证券简称", "简称", "名称"))
            or str(row.get("股票简称", "")).strip()
        )
        listing_date = parse_date(
            first_value_by_label([row], ("上市日期", "上市日", "挂牌日期"))
            or row.get("上市日期")
        )
        if not code or not name or not listing_date:
            continue
        if not is_in_feed_window(listing_date, today):
            continue

        issue_price = (
            normalize_float(first_value_by_label([row], ("发行价", "招股价", "发售价")))
            or normalize_float(row.get("发行价"))
            or normalize_float(row.get("招股价"))
        )
        sector = "港股新股"
        summary = f"{name}为港股 IPO 标的，上市日期为{listing_date.isoformat()}。主营业务和管理层建议以招股书、港交所披露文件及公司公告为准。归类在港股新股板块。"

        output.append(
            {
                "id": f"h-{code}",
                "market": "H",
                "code": code,
                "name": name,
                "exchange": "HKEX",
                "listingDate": listing_date.isoformat(),
                "issuePrice": f"{issue_price} HKD" if issue_price else "待核实",
                "currentPrice": None,
                "sector": sector,
                "tags": ["港股", "港股新股", "同花顺新股"],
                "ceo": "待补充",
                "summary": summary,
                "marketUrl": "https://www.google.com/finance/",
                "searchCode": hk_search_code(code),
                "sourceUrl": "https://stock.10jqka.com.cn/ipo/hk/",
                "sourceName": "同花顺港股 IPO / AKShare"
            }
        )

    return output


def apply_current_prices(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    notes: list[str] = []
    price_map: dict[tuple[str, str], str] = {}

    try:
        import akshare as ak  # type: ignore
    except Exception as exc:
        return items, [f"行情同步失败，沿用上一版现价：{exc}"]

    try:
        df = ak.stock_zh_a_spot_em()
        for row in df.to_dict(orient="records"):
            code = str(row.get("代码", "")).strip().zfill(6)
            price = format_market_price(row.get("最新价"), "CNY")
            if code and price:
                price_map[("A", code)] = price
    except Exception as exc:
        notes.append(f"A股现价同步失败：{exc}")

    try:
        df = ak.stock_hk_spot_em()
        for row in df.to_dict(orient="records"):
            code = str(row.get("代码", "")).strip().zfill(5)
            price = format_market_price(row.get("最新价"), "HKD")
            if code and price:
                price_map[("H", code)] = price
    except Exception as exc:
        notes.append(f"港股现价同步失败：{exc}")

    try:
        df = ak.stock_us_spot_em()
        for row in df.to_dict(orient="records"):
            code = str(row.get("代码", "")).split(".")[-1].strip().upper()
            price = format_market_price(row.get("最新价"), "USD")
            if code and price:
                price_map[("US", code)] = price
    except Exception as exc:
        notes.append(f"美股现价同步失败：{exc}")

    hk_fallback_count = 0
    for item in items:
        market = item.get("market")
        code = str(item.get("code", "")).strip().upper()
        if market == "H":
            code = code.zfill(5)
        elif market == "A":
            code = code.zfill(6)
        if market == "H" and is_listed(item) and ("H", code) not in price_map:
            fallback_price = eastmoney_hk_price(code)
            if fallback_price:
                price_map[("H", code)] = fallback_price
                hk_fallback_count += 1
        if is_listed(item) and (market, code) in price_map:
            item["currentPrice"] = price_map[(market, code)]

    if hk_fallback_count:
        notes.append(f"港股现价已通过东方财富单股备用接口补充 {hk_fallback_count} 条。")

    return items, notes


def merge_items(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for group in groups:
        for item in group:
            market = item.get("market")
            code = str(item.get("code", ""))
            if market in {"A", "H", "US"}:
                item["marketUrl"] = "https://www.google.com/finance/"
            if market == "US" and code:
                item["searchCode"] = code
            if market == "H" and code:
                item["searchCode"] = item.get("searchCode") or f"{code}:HKG"
            if market == "A":
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
        "自动更新：A股新股由东方财富/AKShare 同步；港股 IPO 尝试由同花顺/AKShare 同步；美股 IPO 日历由 StockAnalysis 同步。",
        "上市后的当前价格尝试由东方财富行情同步；行情可能有延迟，交易所与券商页面仍应作为最终核对来源。"
    ]

    try:
        a_items = build_a_items()
    except Exception as exc:
        a_items = [item for item in previous.get("items", []) if item.get("market") == "A"]
        notes.append(f"A股自动同步失败，沿用上一版A股数据：{exc}")

    try:
        h_items = build_h_items()
    except Exception as exc:
        h_items = [item for item in previous.get("items", []) if item.get("market") == "H"]
        notes.append(f"港股自动同步失败，沿用上一版港股数据：{exc}")

    try:
        us_items = build_us_items()
    except Exception as exc:
        us_items = [item for item in previous.get("items", []) if item.get("market") == "US"]
        notes.append(f"美股自动同步失败，沿用上一版美股数据：{exc}")

    items = merge_items(h_items, manual.get("items", []), a_items, us_items)
    items, price_notes = apply_current_prices(items)
    notes.extend(price_notes)
    feed = {
        "updatedAt": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "notes": notes + manual.get("notes", []),
        "items": items
    }
    FEED_PATH.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(items)} IPO records to {FEED_PATH}")


if __name__ == "__main__":
    main()
