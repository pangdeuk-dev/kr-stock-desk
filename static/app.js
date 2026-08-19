const won = (n) => {
  if (n == null || Number.isNaN(n)) return "-";
  return Math.round(n).toLocaleString("ko-KR") + "원";
};
const pct = (n) => {
  if (n == null || Number.isNaN(n)) return "-";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}%`;
};
const tone = (n) => (n > 0 ? "up" : n < 0 ? "down" : "flat");

let selectedTicker = "";
let pollTimer = null;

function showTab(id) {
  document.querySelectorAll(".tab").forEach((el) => el.classList.toggle("on", el.id === `tab-${id}`));
  document.querySelectorAll(".tabs button").forEach((el) => el.classList.toggle("on", el.dataset.tab === id));
}

document.querySelectorAll(".tabs button").forEach((btn) => {
  btn.addEventListener("click", () => showTab(btn.dataset.tab));
});

async function api(path, options) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

function renderIndices(market) {
  const box = document.getElementById("indices");
  const items = [market?.kospi, market?.kosdaq].filter(Boolean);
  box.innerHTML = items
    .map(
      (x) => `
      <div class="idx">
        <span class="muted">${x.name} · ${x.status || ""}</span>
        <b class="${tone(x.change_pct)}">${(x.price ?? 0).toLocaleString("ko-KR")}
          <small>${pct(x.change_pct)}</small>
        </b>
      </div>`
    )
    .join("");
}

function renderKpis(p) {
  const progress = Math.max(0, Math.min(100, (p.monthly_pct / 20) * 100));
  document.getElementById("kpis").innerHTML = `
    <div class="kpi"><span>총자산</span><strong>${won(p.equity)}</strong></div>
    <div class="kpi"><span>평가손익</span><strong class="${tone(p.pnl)}">${won(p.pnl)} (${pct(p.pnl_pct)})</strong></div>
    <div class="kpi"><span>이번 달</span><strong class="${tone(p.monthly_pct)}">${pct(p.monthly_pct)}</strong>
      <div class="bar ${p.monthly_pct < 0 ? "warn" : ""}"><i style="width:${progress}%"></i></div>
      <span>목표 +20% · 월초 ${won(p.month_start_equity)}</span>
    </div>
    <div class="kpi"><span>종목 수</span><strong>${p.name_count} / ${p.max_names}</strong>
      <span>${p.too_many_names ? "분산이 많습니다. 정리하세요." : "현금 " + won(p.cash)}</span>
    </div>`;
}

function renderHoldings(p) {
  const body = document.getElementById("holdings-body");
  if (!p.holdings.length) {
    body.innerHTML = `<tr><td colspan="8" class="muted">아직 등록된 종목이 없습니다. 종목 등록 탭에서 넣으세요.</td></tr>`;
    return;
  }
  body.innerHTML = p.holdings
    .map(
      (h) => `
      <tr>
        <td><b>${h.name}</b><div class="muted">${h.ticker}</div></td>
        <td class="num ${tone(h.change_pct)}">${won(h.price)}</td>
        <td class="num ${tone(h.change_pct)}">${pct(h.change_pct)}</td>
        <td class="num">${won(h.avg_price)}</td>
        <td class="num">${h.qty.toLocaleString("ko-KR")}</td>
        <td class="num">${won(h.value)}</td>
        <td class="num ${tone(h.pnl)}">${won(h.pnl)}<div class="muted">${pct(h.pnl_pct)}</div></td>
        <td class="num">${(h.weight ?? 0).toFixed(1)}%</td>
      </tr>`
    )
    .join("");

  document.getElementById("holding-admin").innerHTML = p.holdings
    .map(
      (h) => `
      <div class="admin-row">
        <div><b>${h.name}</b> ${h.ticker} · ${h.qty}주 · 평단 ${won(h.avg_price)}</div>
        <button class="danger" data-del="${h.id}">삭제</button>
      </div>`
    )
    .join("");
  document.getElementById("cash").value = Math.round(p.cash);
  document.getElementById("month-start").value = Math.round(p.month_start_equity);
}

function actionLabel(a) {
  if (a.action === "BUY") return "매수";
  if (a.action === "SELL") return "매도";
  return "보유";
}

function ticketHtml(a) {
  const extras = [];
  if (a.shares) extras.push(`${a.shares.toLocaleString("ko-KR")}주`);
  if (a.limit_price) extras.push(`지정가 ${won(a.limit_price)}`);
  if (a.amount) extras.push(a.action === "SELL" ? `수령 ${won(a.amount)}` : `사용 ${won(a.amount)}`);
  if (a.avg_after && a.action === "BUY") extras.push(`체결 후 평단 ${won(a.avg_after)}`);
  if (a.qty_after != null && a.action !== "HOLD") extras.push(`체결 후 보유 ${a.qty_after}주`);
  return `
    <div class="action">
      <div class="tag ${a.action}">${actionLabel(a)}</div>
      <div>
        <p class="instruction">${a.instruction || ""}</p>
        <div class="meta">${extras.join(" · ")}</div>
        <div class="muted">${a.reason || ""} ${a.core ? "· 핵심" : ""}</div>
      </div>
    </div>`;
}

function renderOpinion(data) {
  const box = document.getElementById("opinion-box");
  const op = data.opinion;
  const morning = data.morning;
  if (!op && !morning) {
    box.innerHTML = `<div class="card">오늘 생성된 의견이 없습니다. 장중이면 지금 생성하세요.</div>`;
    return;
  }
  const block = (title, item) => {
    if (!item) return "";
    const orders = (item.orders || []).filter((a) => a.shares > 0);
    const rest = (item.actions || []).filter((a) => !orders.some((o) => o.ticker === a.ticker && o.action === a.action && o.shares === a.shares));
    const news = (item.news || [])
      .map((n) => `<li>${n.url ? `<a href="${n.url}" target="_blank" rel="noopener">${n.title}</a>` : n.title} <span class="muted">${n.source || ""}</span></li>`)
      .join("");
    return `
      <div class="card">
        <h2>${title}${item.source === "agent" ? " · 에이전트" : ""}</h2>
        <p>${item.headline || ""}</p>
        <p class="muted">${item.regime_note || ""} · ${item.generated_at || item.created_at || ""}</p>
        ${orders.length ? "<h2>오늘 그대로 실행</h2>" + orders.map(ticketHtml).join("") : "<p class='muted'>오늘은 매수·매도 주문이 없습니다. 보유만 유지하세요.</p>"}
        ${rest.length ? "<h2>보유 지시</h2>" + rest.map(ticketHtml).join("") : ""}
        ${news ? `<h2>참고 뉴스</h2><ul class="news">${news}</ul>` : ""}
        <p class="muted">${item.disclaimer || ""}</p>
      </div>`;
  };
  box.innerHTML = block("11시 투자의견", op) + block("09시 시황", morning);
}

async function loadPortfolio() {
  const p = await api("/api/portfolio");
  renderIndices(p.market);
  renderKpis(p);
  renderHoldings(p);
  document.getElementById("refresh-hint").textContent =
    `시세 ${p.market?.open ? "15초" : "60초"}마다 갱신 · ${p.generated_at || ""}`;
  return p;
}

async function loadOpinions() {
  const data = await api("/api/opinions");
  renderOpinion(data);
}

async function loadJournal() {
  const data = await api("/api/journal");
  document.getElementById("journal-list").innerHTML = data.items
    .map((j) => `<div class="journal-item"><div class="muted">${j.created_at}</div>${j.body}</div>`)
    .join("");
}

function schedulePoll(open) {
  clearInterval(pollTimer);
  pollTimer = setInterval(() => loadPortfolio().catch(console.error), open ? 15000 : 60000);
}

document.getElementById("holding-admin").addEventListener("click", async (e) => {
  const id = e.target.dataset.del;
  if (!id) return;
  await api(`/api/holdings/${id}`, { method: "DELETE" });
  await loadPortfolio();
});

let searchTimer;
document.getElementById("q").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(async () => {
    const q = document.getElementById("q").value.trim();
    const hits = document.getElementById("search-hits");
    if (!q) {
      hits.innerHTML = "";
      return;
    }
    const data = await api(`/api/search?q=${encodeURIComponent(q)}`);
    hits.innerHTML = data.items
      .map(
        (x) =>
          `<button type="button" data-ticker="${x.ticker}" data-name="${x.name}">${x.name} (${x.ticker}) ${pct(x.change_pct)}</button>`
      )
      .join("");
  }, 250);
});

document.getElementById("search-hits").addEventListener("click", (e) => {
  const btn = e.target.closest("button");
  if (!btn) return;
  selectedTicker = btn.dataset.ticker;
  document.getElementById("ticker").value = btn.dataset.ticker;
  document.getElementById("name").value = btn.dataset.name;
});

document.getElementById("holding-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/holdings", {
      method: "POST",
      body: JSON.stringify({
        ticker: document.getElementById("ticker").value,
        name: document.getElementById("name").value,
        qty: Number(document.getElementById("qty").value),
        avg_price: Number(document.getElementById("avg").value),
        memo: document.getElementById("memo").value,
      }),
    });
    e.target.reset();
    document.getElementById("search-hits").innerHTML = "";
    await loadPortfolio();
    showTab("board");
  } catch (err) {
    alert(err.message);
  }
});

document.getElementById("cash-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  await api("/api/settings/cash", {
    method: "POST",
    body: JSON.stringify({ cash: Number(document.getElementById("cash").value || 0) }),
  });
  await api("/api/settings/month-start", {
    method: "POST",
    body: JSON.stringify({ month_start_equity: Number(document.getElementById("month-start").value || 0) }),
  });
  await loadPortfolio();
  alert("설정을 저장했습니다.");
});

document.getElementById("journal-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  await api("/api/journal", {
    method: "POST",
    body: JSON.stringify({ body: document.getElementById("journal-body").value }),
  });
  document.getElementById("journal-body").value = "";
  await loadJournal();
});

document.getElementById("btn-morning").addEventListener("click", async () => {
  await api("/api/opinions/generate?kind=morning", { method: "POST" });
  await loadOpinions();
});
document.getElementById("btn-opinion").addEventListener("click", async () => {
  await api("/api/opinions/generate?kind=opinion", { method: "POST" });
  await loadOpinions();
});

(async function init() {
  const p = await loadPortfolio();
  await loadOpinions();
  await loadJournal();
  schedulePoll(Boolean(p.market?.open));
})();
