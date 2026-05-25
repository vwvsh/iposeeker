from __future__ import annotations

import json
import os
import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
FEED_PATH = ROOT / "data" / "ipo-feed.json"
TZ = ZoneInfo("Asia/Shanghai")


def days_from_today(date_value: str) -> int:
    today = datetime.now(TZ).date()
    listing_date = datetime.fromisoformat(date_value).date()
    return (listing_date - today).days


def market_name(market: str) -> str:
    return {"A": "A股", "H": "H股", "US": "美股"}.get(market, market)


def brief_lines(feed: dict) -> list[str]:
    items = feed.get("items", [])
    upcoming = [item for item in items if 0 <= days_from_today(item["listingDate"]) <= 3]
    listed = [item for item in items if days_from_today(item["listingDate"]) < 0]
    watch = upcoming[:3]

    lines = [
        "IPO Seeker 每日简报",
        "",
        f"生成时间：{datetime.now(TZ).strftime('%Y-%m-%d %H:%M')}",
        f"数据更新时间：{feed.get('updatedAt', '未知')}",
        "",
        f"未来 3 天即将上市：{len(upcoming)} 只",
    ]

    if upcoming:
        for item in upcoming:
            lines.append(
                f"- [{market_name(item['market'])}] {item['code']} {item['name']}，"
                f"{item['listingDate']}，发行价 {item.get('issuePrice') or '待核实'}，"
                f"板块：{item.get('sector', '待核实')}"
            )
    else:
        lines.append("- 暂无未来 3 天内上市记录。")

    lines += ["", "最新已上市记录："]
    if listed:
        for item in sorted(listed, key=lambda row: row["listingDate"], reverse=True)[:5]:
            lines.append(
                f"- [{market_name(item['market'])}] {item['code']} {item['name']}，"
                f"{item['listingDate']}，当前价 {item.get('currentPrice') or '待核实'}"
            )
    else:
        lines.append("- 暂无已上市历史记录。")

    lines += ["", "今天重点关注："]
    if watch:
        for item in watch:
            reason = item.get("summary", "关注上市前发行价、板块热度和首日成交表现。")
            lines.append(f"- {item['code']} {item['name']}：{reason}")
    else:
        lines.append("- 今天没有新的重点标的。")

    pending = [
        item
        for item in items
        if "待核实" in " ".join(str(value) for value in item.values() if value is not None)
    ]
    lines += ["", f"待核实项：{len(pending)} 条"]
    if pending:
        lines.append("建议查看网页中的来源链接确认 CEO、发行价或现价。")

    lines += ["", "网站：https://vwvsh.github.io/iposeeker/"]
    return lines


def main() -> None:
    username = os.environ["MAIL_USERNAME"]
    password = os.environ["MAIL_PASSWORD"]
    recipient = os.environ.get("MAIL_TO", "vikinginshanghai@qq.com")
    server = os.environ.get("SMTP_SERVER", "smtp.qq.com")
    port = int(os.environ.get("SMTP_PORT", "465"))

    feed = json.loads(FEED_PATH.read_text(encoding="utf-8"))
    body = "\n".join(brief_lines(feed))

    msg = EmailMessage()
    msg["Subject"] = f"IPO Seeker 每日简报 {datetime.now(TZ).strftime('%Y-%m-%d')}"
    msg["From"] = username
    msg["To"] = recipient
    msg.set_content(body)

    with smtplib.SMTP_SSL(server, port, timeout=30) as smtp:
        smtp.login(username, password)
        smtp.send_message(msg)

    print(f"Sent daily brief to {recipient}")


if __name__ == "__main__":
    main()
