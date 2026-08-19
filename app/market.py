from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from typing import Any

import httpx

NAVER = "https://m.stock.naver.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://m.stock.naver.com/",
}

_universe_cache: dict[str, Any] = {"at": 0.0, "items": []}


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").replace("%", "").strip()
    if text in {"", "-", "N/A"}:
        return None
    return float(text)


def _get(path: str, timeout: float = 12.0) -> Any:
    url = path if path.startswith("http") else f"{NAVER}{path}"
    with httpx.Client(headers=HEADERS, timeout=timeout, follow_redirects=True) as client:
        res = client.get(url)
        res.raise_for_status()
        return res.json()


def quote(ticker: str) -> dict:
    code = ticker.strip().zfill(6)
    data = _get(f"/api/stock/{code}/basic")
    change_info = data.get("compareToPreviousPrice") or {}
    exchange = data.get("stockExchangeType") or {}
    if isinstance(exchange, dict):
        exchange_name = exchange.get("name") or exchange.get("code") or ""
    else:
        exchange_name = str(exchange or data.get("stockExchangeName") or "")
    return {
        "ticker": data.get("itemCode") or code,
        "name": data.get("stockName") or code,
        "price": _num(data.get("closePrice")),
        "change": _num(data.get("compareToPreviousClosePrice")),
        "change_pct": _num(data.get("fluctuationsRatio")),
        "status": data.get("marketStatus") or "",
        "exchange": exchange_name,
        "direction": change_info.get("name") if isinstance(change_info, dict) else "",
        "traded_at": data.get("localTradedAt") or "",
    }


def quotes(tickers: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for raw in tickers:
        code = raw.strip().zfill(6)
        if not code:
            continue
        try:
            out[code] = quote(code)
        except Exception as exc:
            out[code] = {
                "ticker": code,
                "name": code,
                "price": None,
                "change": None,
                "change_pct": None,
                "status": "ERROR",
                "error": str(exc),
            }
    return out


def index(code: str) -> dict:
    data = _get(f"/api/index/{code}/basic")
    return {
        "code": data.get("itemCode") or code,
        "name": data.get("stockName") or code,
        "price": _num(data.get("closePrice")),
        "change": _num(data.get("compareToPreviousClosePrice")),
        "change_pct": _num(data.get("fluctuationsRatio")),
        "status": data.get("marketStatus") or "",
        "traded_at": data.get("localTradedAt") or "",
    }


def market_snapshot() -> dict:
    kospi = index("KOSPI")
    kosdaq = index("KOSDAQ")
    status = kospi.get("status") or kosdaq.get("status") or ""
    return {
        "kospi": kospi,
        "kosdaq": kosdaq,
        "status": status,
        "open": status.upper() == "OPEN",
    }


def _page_universe(sosok: int, page: int, page_size: int = 100) -> list[dict]:
    data = _get(
        "/api/json/sise/siseListJson.nhn"
        f"?menu=market_sum&sosok={sosok}&pageSize={page_size}&page={page}"
    )
    items = (data.get("result") or {}).get("itemList") or []
    rows = []
    for item in items:
        ticker = str(item.get("cd") or "").zfill(6)
        if not ticker.isdigit():
            continue
        market = "KOSPI" if item.get("kospi") else "KOSDAQ" if item.get("kosdaq") else ""
        rows.append(
            {
                "ticker": ticker,
                "name": item.get("nm") or ticker,
                "price": _num(item.get("nv")),
                "change_pct": _num(item.get("cr")),
                "market": market,
                "value": item.get("mks") or 0,
            }
        )
    return rows


def stock_universe(force: bool = False) -> list[dict]:
    now = time.time()
    if not force and _universe_cache["items"] and now - _universe_cache["at"] < 6 * 3600:
        return _universe_cache["items"]
    rows: list[dict] = []
    seen: set[str] = set()
    for sosok in (0, 1):
        for page in range(1, 6):
            chunk = _page_universe(sosok, page)
            if not chunk:
                break
            for row in chunk:
                if row["ticker"] in seen:
                    continue
                seen.add(row["ticker"])
                rows.append(row)
    rows.sort(key=lambda r: r.get("value") or 0, reverse=True)
    _universe_cache["at"] = now
    _universe_cache["items"] = rows
    return rows


def _news_from_naver(limit: int) -> list[dict]:
    data = _get("/front-api/news?pageSize=12", timeout=12.0)
    rows = []
    blob = data
    if isinstance(data, dict):
        blob = (
            data.get("result")
            or data.get("news")
            or data.get("newsList")
            or data.get("items")
            or data
        )
    if isinstance(blob, dict):
        blob = blob.get("newsList") or blob.get("list") or blob.get("items") or []
    if not isinstance(blob, list):
        return []
    for item in blob:
        if not isinstance(item, dict):
            continue
        title = item.get("title") or item.get("newsTitle") or ""
        if not title:
            continue
        rows.append(
            {
                "title": title.replace("<b>", "").replace("</b>", ""),
                "source": item.get("officeName") or item.get("source") or "네이버",
                "url": item.get("link") or item.get("url") or item.get("endUrl") or "",
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _news_from_rss(limit: int) -> list[dict]:
    url = (
        "https://news.google.com/rss/search"
        "?q=%EC%BD%94%EC%8A%A4%ED%94%BC+OR+%EA%B5%AD%EB%82%B4%EC%A3%BC%EC%8B%9D"
        "&hl=ko&gl=KR&ceid=KR:ko"
    )
    with httpx.Client(headers=HEADERS, timeout=12.0, follow_redirects=True) as client:
        res = client.get(url)
        res.raise_for_status()
        root = ET.fromstring(res.text)
    rows = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        source = (item.findtext("source") or "뉴스").strip()
        if not title:
            continue
        rows.append({"title": title, "source": source, "url": link})
        if len(rows) >= limit:
            break
    return rows


def market_news(limit: int = 8) -> list[dict]:
    try:
        rows = _news_from_naver(limit)
        if rows:
            return rows
    except Exception:
        pass
    try:
        return _news_from_rss(limit)
    except Exception:
        return []


def search_stocks(query: str, limit: int = 12) -> list[dict]:
    q = query.strip()
    if not q:
        return []
    if q.isdigit():
        code = q.zfill(6)
        try:
            item = quote(code)
            return [
                {
                    "ticker": item["ticker"],
                    "name": item["name"],
                    "price": item["price"],
                    "change_pct": item["change_pct"],
                    "market": item.get("exchange") or "",
                }
            ]
        except Exception:
            return []
    q_lower = q.lower()
    hits = []
    for row in stock_universe():
        if q_lower in row["name"].lower() or q_lower in row["ticker"]:
            hits.append(row)
        if len(hits) >= limit:
            break
    return hits
