const DATA_URL = "./data/ipo-feed.json";
const FAVORITES_KEY = "ipo-radar:favorites";
const CACHE_KEY = "ipo-radar:feed-cache:v9";;
const LAST_CHECK_KEY = "ipo-radar:last-check";

const fallbackFeed = {
  updatedAt: new Date().toISOString(),
  notes: ["数据文件加载失败，因此没有显示任何股票；请用本地服务器打开页面。"],
  items: []
};

const state = {
  feed: fallbackFeed,
  favorites: new Set(JSON.parse(localStorage.getItem(FAVORITES_KEY) || "[]")),
  view: "upcoming",
  markets: new Set(["A", "H", "US"]),
  query: ""
};

const elements = {
  grid: document.querySelector("#stock-grid"),
  template: document.querySelector("#stock-card-template"),
  search: document.querySelector("#search-input"),
  viewButtons: document.querySelectorAll("[data-view]"),
  marketInputs: document.querySelectorAll(".market-filter input"),
  empty: document.querySelector("#empty-state"),
  boardTitle: document.querySelector("#board-title"),
  refresh: document.querySelector("#refresh-button"),
  feedStatus: document.querySelector("#feed-status"),
  feedTime: document.querySelector("#feed-time"),
  metricUpcoming: document.querySelector("#metric-upcoming"),
  metricFavorites: document.querySelector("#metric-favorites"),
  metricHistory: document.querySelector("#metric-history")
};

function todayKey() {
  return new Date().toISOString().slice(0, 10);
}

function daysFromToday(dateValue) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const date = new Date(`${dateValue}T00:00:00`);
  return Math.round((date - today) / 86400000);
}

function isUpcomingSoon(stock) {
  const days = daysFromToday(stock.listingDate);
  return days >= 0 && days <= 3;
}

function isListed(stock) {
  return daysFromToday(stock.listingDate) < 0;
}

function marketLabel(market) {
  return { A: "A 股", H: "H 股", US: "美股" }[market] || market;
}

function symbolForSearch(stock) {
  if (stock.searchCode) return stock.searchCode;
  if (stock.market === "US") return stock.code;
  if (stock.market === "H") return `${stock.code}:HKG`;
  if (stock.exchange.includes("上交所") || stock.exchange.includes("科创")) return `${stock.code}:SHA`;
  if (stock.exchange.includes("深交所") || stock.exchange.includes("创业")) return `${stock.code}:SHE`;
  if (stock.exchange.includes("北交所")) return `${stock.code}:BJS`;
  return stock.code;
}

function setMarketLink(link, stock) {
  link.href = "https://www.google.com/finance/";
  link.textContent = "打开 Google 财经";
  link.setAttribute("aria-label", "打开 Google 财经后粘贴股票代码搜索");
  link.classList.remove("is-disabled");
}

async function copyText(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.append(textarea);
  textarea.select();
  document.execCommand("copy");
  textarea.remove();
}

function formatDate(dateValue) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    weekday: "short"
  }).format(new Date(`${dateValue}T00:00:00`));
}

function matchesQuery(stock) {
  if (!state.query) return true;
  const haystack = [
    stock.code,
    stock.name,
    stock.exchange,
    stock.sector,
    stock.summary,
    stock.ceo,
    stock.sourceName,
    ...(stock.tags || [])
  ].join(" ").toLowerCase();
  return haystack.includes(state.query.toLowerCase());
}

function filteredItems() {
  return state.feed.items
    .filter((stock) => state.markets.has(stock.market))
    .filter(matchesQuery)
    .filter((stock) => {
      if (state.view === "upcoming") return isUpcomingSoon(stock);
      if (state.view === "favorites") return state.favorites.has(stock.id);
      if (state.view === "history") return isListed(stock);
      return true;
    })
    .sort((a, b) => new Date(a.listingDate) - new Date(b.listingDate));
}

function saveFavorites() {
  localStorage.setItem(FAVORITES_KEY, JSON.stringify([...state.favorites]));
}

function setView(view) {
  state.view = view;
  elements.viewButtons.forEach((button) => {
    button.classList.toggle("is-active", button.dataset.view === view);
  });
  render();
}

function renderMetrics() {
  const all = state.feed.items;
  elements.metricUpcoming.textContent = all.filter(isUpcomingSoon).length;
  elements.metricFavorites.textContent = state.favorites.size;
  elements.metricHistory.textContent = all.filter(isListed).length;
}

function renderStatus(source = "本地数据") {
  const updatedAt = state.feed.updatedAt ? new Date(state.feed.updatedAt) : null;
  elements.feedStatus.textContent = source;
  elements.feedTime.textContent = updatedAt
    ? `更新于 ${new Intl.DateTimeFormat("zh-CN", {
        dateStyle: "medium",
        timeStyle: "short"
      }).format(updatedAt)}`
    : "等待首次同步";
}

function renderCard(stock) {
  const fragment = elements.template.content.cloneNode(true);
  const card = fragment.querySelector(".stock-card");
  const badge = fragment.querySelector(".market-badge");
  const favorite = fragment.querySelector(".favorite-button");

  badge.textContent = marketLabel(stock.market);
  badge.classList.toggle("market-h", stock.market === "H");
  badge.classList.toggle("market-us", stock.market === "US");
  fragment.querySelector("h3").textContent = stock.nameZh || stock.name;
  fragment.querySelector(".code-line").textContent = `${stock.code} · ${stock.exchange}`;
  fragment.querySelector(".summary").textContent = stock.summary;
  fragment.querySelector(".ceo-name").textContent = stock.ceo || "待补充";
  fragment.querySelector(".issue-price").textContent = stock.issuePrice || "--";
  fragment.querySelector(".listing-date").textContent = formatDate(stock.listingDate);
 fragment.querySelector(".current-price").textContent =
  stock.currentPrice || (isListed(stock) ? "待核实" : "待上市");
  const tags = fragment.querySelector(".tags");
  [stock.sector, ...(stock.tags || [])].forEach((tag) => {
    const pill = document.createElement("span");
    pill.className = "tag";
    pill.textContent = tag;
    tags.append(pill);
  });

  const saved = state.favorites.has(stock.id);
  favorite.textContent = saved ? "★" : "☆";
  favorite.classList.toggle("is-saved", saved);
  favorite.setAttribute("aria-label", saved ? "取消收藏" : "收藏");
  favorite.addEventListener("click", () => {
    if (state.favorites.has(stock.id)) {
      state.favorites.delete(stock.id);
    } else {
      state.favorites.add(stock.id);
    }
    saveFavorites();
    render();
  });

  const days = daysFromToday(stock.listingDate);
  if (days === 0) card.dataset.status = "today";
  if (days < 0) card.dataset.status = "listed";

  const marketLink = fragment.querySelector(".market-link");
  setMarketLink(marketLink, stock);

  const copyButton = fragment.querySelector(".copy-code-button");
  const queryCode = symbolForSearch(stock);
  copyButton.textContent = `复制 ${queryCode}`;
  copyButton.addEventListener("click", async () => {
    await copyText(queryCode);
    copyButton.textContent = "已复制";
    setTimeout(() => {
      copyButton.textContent = `复制 ${queryCode}`;
    }, 1400);
  });

  const sourceLink = fragment.querySelector(".source-link");
  if (stock.sourceUrl) {
    sourceLink.href = stock.sourceUrl;
    sourceLink.textContent = `查看资料来源：${stock.sourceName || "公开资料"}`;
  } else {
    sourceLink.removeAttribute("href");
    sourceLink.textContent = "来源：待核实";
  }
  return fragment;
}

function render() {
  const titles = {
    upcoming: "3 天内即将交易",
    favorites: "收藏观察",
    history: "已上市历史",
    all: "全部新股"
  };
  elements.boardTitle.textContent = titles[state.view];
  elements.grid.replaceChildren();
  const items = filteredItems();
  items.forEach((stock) => elements.grid.append(renderCard(stock)));
  elements.empty.hidden = items.length > 0;
  renderMetrics();
  renderStatus("数据已就绪");
}

async function refreshFeed({ force = false } = {}) {
const cached = localStorage.getItem(CACHE_KEY);

try {
    elements.feedStatus.textContent = "正在同步数据";
    const response = await fetch(DATA_URL, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const nextFeed = await response.json();
    state.feed = nextFeed;
    localStorage.setItem(CACHE_KEY, JSON.stringify(nextFeed));
    localStorage.setItem(LAST_CHECK_KEY, todayKey());
    renderStatus("数据已同步");
  } catch (error) {
    const cachedFeed = cached ? JSON.parse(cached) : fallbackFeed;
    state.feed = cachedFeed;
    renderStatus(cached ? "使用缓存数据" : "使用示例数据");
  }

  render();
}

elements.search.addEventListener("input", (event) => {
  state.query = event.target.value.trim();
  render();
});

elements.viewButtons.forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.view));
});

elements.marketInputs.forEach((input) => {
  input.addEventListener("change", () => {
    state.markets = new Set(
      [...elements.marketInputs].filter((item) => item.checked).map((item) => item.value)
    );
    render();
  });
});

elements.refresh.addEventListener("click", () => refreshFeed({ force: true }));

refreshFeed();
setInterval(() => refreshFeed(), 60 * 60 * 1000);
