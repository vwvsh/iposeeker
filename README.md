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

前端默认读取 `data/ipo-feed.json`，并按自然日缓存。部署后可以用任意定时任务每天生成这个 JSON 文件，字段格式如下：

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

推荐后续接入：

- A 股：上交所、深交所、北交所新股日历，或券商/财经数据 API。
- H 股：HKEX 新股/FINI 相关数据，或港股行情数据 API。
- 美股：Nasdaq IPO Calendar、NYSE IPO Center、SEC filings，或聚合行情 API。

当前仓库里的样例数据用于演示界面和交互，不代表真实行情。
