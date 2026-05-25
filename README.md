# IPO Radar

一个黑色科技风的新股观察台，用于查看 A 股、H 股、美股未来 3 天内即将上市交易的股票，并保留收藏、已上市历史和代码搜索。

## 运行

在当前目录启动一个静态服务器：

```powershell
python -m http.server 4173
```

然后访问 `http://localhost:4173`。

如果系统没有全局 `python`，也可以用 Codex 捆绑运行时：

```powershell
& "C:\Users\vikin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m http.server 4173
```

## 数据更新

前端默认读取 `data/ipo-feed.json`，并按自然日缓存。

仓库包含 GitHub Actions 定时任务：

- `.github/workflows/update-ipo-feed.yml`
- `scripts/update_ipo_feed.py`
- `data/manual-ipo-overrides.json`

它会在每天 06:30（北京时间）自动运行，更新 `data/ipo-feed.json` 并提交到仓库。也可以在 GitHub 仓库的 `Actions` 页面手动运行 `Update IPO Feed`。

仓库还包含每日邮件简报任务：

- `.github/workflows/daily-email-brief.yml`
- `scripts/send_daily_brief.py`

它会在每天 09:00（北京时间）发送中文简报到配置的收件邮箱。使用前需要在 GitHub 仓库 `Settings -> Secrets and variables -> Actions` 添加：

- `MAIL_USERNAME`：发件邮箱地址
- `MAIL_PASSWORD`：发件邮箱 SMTP 授权码，不是登录密码

当前自动同步逻辑：

- 美股：自动读取 StockAnalysis IPO Calendar，并补充公司页 CEO、行业和简介。
- 港股/A股：暂由 `data/manual-ipo-overrides.json` 补充，避免未验证来源自动生成错误行情。

字段格式如下：

```json
{
  "updatedAt": "2026-05-25T08:00:00+08:00",
  "items": [
    {
      "id": "us-demo",
      "market": "US",
      "code": "DEMO",
      "name": "Demo Inc.",
      "exchange": "NASDAQ",
      "listingDate": "2026-05-28",
      "issuePrice": "16.00 USD",
      "currentPrice": null,
      "sector": "软件服务",
      "tags": ["企业 AI", "NASDAQ"],
      "summary": "一两句话说明主营产品、经营范围和所属板块。"
    }
  ]
}
```

推荐后续增强：

- A 股：上交所、深交所、北交所新股日历，或券商/财经数据 API。
- H 股：HKEX 新股/FINI 相关数据，或港股行情数据 API。
- 美股：Nasdaq IPO Calendar、NYSE IPO Center、SEC filings，或聚合行情 API。
