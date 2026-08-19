from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app import db, market

KST = ZoneInfo("Asia/Seoul")
MAX_NAMES = 6
CORE_TICKERS = {
    "005930",
    "000660",
    "005380",
    "035420",
    "035720",
    "051910",
    "006400",
    "068270",
    "105560",
    "055550",
    "012330",
    "207940",
}
BRIEFINGS = Path(__file__).resolve().parent.parent / "briefings"


def _won(n: float | int | None) -> str:
    if n is None:
        return "-"
    return f"{int(round(n)):,}원"


def _regime(kospi_pct: float | None) -> tuple[str, str]:
    pct = kospi_pct or 0.0
    if pct <= -4:
        return "risk_off", "코스피가 크게 빠지고 있습니다. 신규 공격 매수보다 현금·핵심 보유가 우선입니다."
    if pct <= -2:
        return "cautious", "시장이 약합니다. 추격 매수는 피하고, 보유 종목은 원칙대로 재확인하세요."
    if pct >= 2:
        return "risk_on", "시장이 강합니다. 핵심 1~2개에만 추격하지 말고 분할로 대응하는 편이 낫습니다."
    return "neutral", "방향이 뚜렷하지 않습니다. 보유가 기본이고, 확신이 있는 자리만 조정하세요."


def _limit_price(price: float | None) -> int | None:
    if not price:
        return None
    return int(round(price))


def _shares_for(price: int, budget: float) -> int:
    if price <= 0 or budget < price:
        return 0
    return int(budget // price)


def _avg_after(qty: float, avg: float, add_qty: int, add_price: int) -> float | None:
    total = qty + add_qty
    if total <= 0:
        return avg
    return (qty * avg + add_qty * add_price) / total


def _ticket(
    *,
    ticker: str,
    name: str,
    action: str,
    reason: str,
    price: float | None,
    qty: float = 0,
    avg: float = 0,
    shares: int = 0,
    core: bool = False,
    change_pct: float | None = None,
    pnl_pct: float | None = None,
    weight: float = 0,
) -> dict:
    limit = _limit_price(price)
    amount = int(shares * limit) if limit and shares else 0
    qty_after = qty
    avg_after = avg
    if action in {"BUY", "AVG"} and shares > 0 and limit:
        qty_after = qty + shares
        avg_after = _avg_after(qty, avg, shares, limit)
    elif action == "SELL" and shares > 0:
        qty_after = max(0, qty - shares)
        avg_after = avg if qty_after else None

    if shares <= 0 and action in {"BUY", "AVG"}:
        instruction = (
            f"{name}({ticker}) 매수를 원했지만 예수금이 부족합니다. "
            f"종목 등록에서 실제 예수금을 입력한 뒤 의견을 다시 생성하세요. "
            f"지금은 {int(qty)}주, 평단 {_won(avg)} 그대로 보유하세요."
        )
        action = "HOLD"
        shares = 0
        amount = 0
    elif action == "HOLD" or shares <= 0:
        instruction = (
            f"{name}({ticker})는 매매하지 마세요. "
            f"현재 {int(qty)}주, 평단 {_won(avg)} 그대로 유지합니다."
        )
        action = "HOLD"
        shares = 0
        amount = 0
    elif action == "SELL":
        instruction = (
            f"{name}({ticker})를 지정가 {_won(limit)}에 {shares}주 매도하세요. "
            f"예상 수령 {_won(amount)}. 체결 후 잔량 {int(qty_after)}주, 평단은 {_won(avg)} 그대로입니다."
        )
    elif action == "AVG":
        instruction = (
            f"{name}({ticker})를 지정가 {_won(limit)}에 {shares}주 추가 매수해 평단을 맞추세요. "
            f"사용 {_won(amount)}. 체결 후 보유 {int(qty_after)}주, 목표 평단 {_won(avg_after)}입니다."
        )
        action = "BUY"
    else:
        instruction = (
            f"{name}({ticker})를 지정가 {_won(limit)}에 {shares}주 매수하세요. "
            f"사용 {_won(amount)}. 체결 후 보유 {int(qty_after)}주, 평단 {_won(avg_after)}입니다."
        )

    return {
        "ticker": ticker,
        "name": name,
        "action": action,
        "reason": reason,
        "instruction": instruction,
        "limit_price": limit,
        "shares": shares,
        "amount": amount,
        "qty_now": qty,
        "qty_after": qty_after,
        "avg_now": avg,
        "avg_after": avg_after,
        "core": core,
        "change_pct": change_pct,
        "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
        "weight": round(weight, 2),
        "price": price,
    }


def _decide_holding(row: dict, kospi_pct: float | None, regime: str) -> str:
    change_pct = row.get("change_pct") or 0
    pnl_pct = row.get("pnl_pct")
    ticker = row["ticker"]
    is_core = ticker in CORE_TICKERS
    weight = row.get("weight") or 0
    if pnl_pct is not None and pnl_pct <= -18 and change_pct <= -6 and not is_core:
        return "SELL"
    if regime == "risk_off" and not is_core and change_pct <= -5:
        return "SELL"
    if (
        regime in {"cautious", "neutral", "risk_on"}
        and is_core
        and pnl_pct is not None
        and -12 <= pnl_pct <= 8
        and weight < 28
        and (kospi_pct or 0) <= -2
        and change_pct <= -3
    ):
        return "AVG"
    if pnl_pct is not None and pnl_pct >= 30 and change_pct >= 4:
        return "SELL"
    return "HOLD"


def _new_ideas(held: set[str], regime: str, slots: int) -> list[dict]:
    if slots <= 0 or regime == "risk_off":
        return []
    ideas = []
    satellite_used = False
    for row in market.stock_universe():
        ticker = row["ticker"]
        if ticker in held:
            continue
        change = row.get("change_pct") or 0
        is_core = ticker in CORE_TICKERS
        if regime == "cautious" and not is_core:
            continue
        if is_core and -8 <= change <= -1.5:
            ideas.append({**row, "action": "BUY", "core": True,
                          "reason": "거래대금 상위 핵심 종목이 밀린 자리입니다."})
        elif (
            not is_core
            and not satellite_used
            and regime in {"neutral", "risk_on"}
            and 1.2 <= change <= 4.5
        ):
            satellite_used = True
            ideas.append({**row, "action": "BUY", "core": False,
                          "reason": "위험 감수 한도 안의 위성 후보입니다. 전체의 10%를 넘기지 마세요."})
        if len(ideas) >= slots:
            break
    return ideas[:slots]


def _size_orders(view: dict, regime: str, kospi_pct: float | None, kind: str) -> list[dict]:
    cash = float(view.get("cash") or 0)
    equity = float(view.get("equity") or 0)
    tickets: list[dict] = []
    held = {row["ticker"] for row in view["holdings"]}

    for row in view["holdings"]:
        action = "HOLD" if kind == "morning" else _decide_holding(row, kospi_pct, regime)
        price = row.get("price") or 0
        qty = row.get("qty") or 0
        avg = row.get("avg_price") or 0
        shares = 0
        if action == "SELL" and qty > 0:
            shares = max(1, int(qty * 0.33))
            if shares >= qty:
                shares = int(qty)
        elif action == "AVG" and price:
            budget = min(cash * 0.35, equity * 0.08 if equity else cash * 0.35)
            shares = _shares_for(int(price), budget)
            if shares:
                cash -= shares * int(price)
        tickets.append(
            _ticket(
                ticker=row["ticker"],
                name=row.get("name") or row["ticker"],
                action=action,
                reason=(
                    "장 시작 스냅샷입니다. 11시 의견 전까지 매매하지 마세요."
                    if kind == "morning"
                    else {
                        "SELL": "비중을 줄여 현금을 확보합니다.",
                        "AVG": "핵심 종목 평단을 낮추기 위한 분할 매수입니다.",
                        "HOLD": "특별한 이탈 신호가 없어 보유가 낫습니다.",
                    }.get(action, "")
                ),
                price=price,
                qty=qty,
                avg=avg,
                shares=shares,
                core=row["ticker"] in CORE_TICKERS,
                change_pct=row.get("change_pct"),
                pnl_pct=row.get("pnl_pct"),
                weight=row.get("weight") or 0,
            )
        )

    if kind == "morning":
        return tickets

    buy_holdings = sum(1 for t in tickets if t["action"] == "BUY")
    slots = max(0, MAX_NAMES - len(held) - (1 if buy_holdings else 0))
    for idea in _new_ideas(held, regime, min(2, slots)):
        price = idea.get("price") or 0
        cap = 0.10 if not idea.get("core") else 0.12
        budget = min(cash * 0.30, equity * cap if equity else cash * 0.30)
        shares = _shares_for(int(price), budget) if price else 0
        if shares:
            cash -= shares * int(price)
        tickets.append(
            _ticket(
                ticker=idea["ticker"],
                name=idea["name"],
                action="BUY",
                reason=idea["reason"],
                price=price,
                qty=0,
                avg=0,
                shares=shares,
                core=bool(idea.get("core")),
                change_pct=idea.get("change_pct"),
            )
        )
        held.add(idea["ticker"])
    return tickets


def _apply_research(tickets: list[dict], view: dict, research: dict) -> list[dict]:
    calls = research.get("calls") or []
    if not calls:
        return tickets
    by_ticker = {t["ticker"]: t for t in tickets}
    cash = float(view.get("cash") or 0)
    equity = float(view.get("equity") or 0)
    holdings = {h["ticker"]: h for h in view["holdings"]}
    out = []
    used = set()
    for call in calls:
        ticker = str(call.get("ticker") or "").zfill(6)
        action = (call.get("action") or "HOLD").upper()
        if action == "AVG":
            action = "BUY"
        h = holdings.get(ticker)
        price = call.get("limit_price") or (h or {}).get("price") or 0
        qty = (h or {}).get("qty") or 0
        avg = (h or {}).get("avg_price") or 0
        name = call.get("name") or (h or {}).get("name") or ticker
        shares = 0
        mapped = "HOLD"
        if action == "SELL" and qty:
            mapped = "SELL"
            shares = max(1, int(qty * 0.33))
            if shares >= qty:
                shares = int(qty)
        elif action == "BUY" and price:
            mapped = "AVG" if qty else "BUY"
            budget = min(cash * 0.30, equity * 0.08 if equity else cash * 0.30)
            shares = _shares_for(int(price), budget)
            if shares:
                cash -= shares * int(price)
        ticket = _ticket(
            ticker=ticker,
            name=name,
            action=mapped,
            reason=call.get("reason") or "에이전트 리서치 반영",
            price=price,
            qty=qty,
            avg=avg,
            shares=shares,
            core=ticker in CORE_TICKERS,
            change_pct=(h or {}).get("change_pct"),
            pnl_pct=(h or {}).get("pnl_pct"),
            weight=(h or {}).get("weight") or 0,
        )
        out.append(ticket)
        used.add(ticker)
    for ticket in tickets:
        if ticket["ticker"] not in used:
            out.append(ticket)
    return out


def load_research() -> dict | None:
    path = BRIEFINGS / f"{db.today_kst()}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def build_portfolio_view() -> dict:
    holdings = db.list_holdings()
    cash = float(db.get_setting("cash") or 0)
    tickers = [h["ticker"] for h in holdings]
    qmap = market.quotes(tickers) if tickers else {}
    snap = market.market_snapshot()
    rows = []
    invested = 0.0
    market_value = 0.0
    for h in holdings:
        q = qmap.get(h["ticker"], {})
        price = q.get("price") or 0
        qty = h["qty"]
        cost = qty * h["avg_price"]
        value = qty * price
        invested += cost
        market_value += value
        rows.append(
            {
                **h,
                **{k: q.get(k) for k in ("price", "change", "change_pct", "status", "exchange", "traded_at")},
                "cost": cost,
                "value": value,
                "pnl": value - cost,
                "pnl_pct": ((value - cost) / cost * 100) if cost else None,
            }
        )
    equity = cash + market_value
    for row in rows:
        row["weight"] = (row["value"] / equity * 100) if equity else 0
    month = db.month_key()
    stored_month = db.get_setting("month_key")
    start = db.get_setting("month_start_equity")
    if stored_month != month or not start:
        db.set_setting("month_key", month)
        db.set_setting("month_start_equity", str(round(equity, 0)))
        start = str(round(equity, 0))
    start_equity = float(start or 0)
    monthly_pnl = equity - start_equity if start_equity else 0
    monthly_pct = (monthly_pnl / start_equity * 100) if start_equity else 0
    return {
        "cash": cash,
        "invested": invested,
        "market_value": market_value,
        "equity": equity,
        "pnl": market_value - invested,
        "pnl_pct": ((market_value - invested) / invested * 100) if invested else 0,
        "month_key": month,
        "month_start_equity": start_equity,
        "monthly_pnl": monthly_pnl,
        "monthly_pct": monthly_pct,
        "monthly_target_pct": 20,
        "holdings": rows,
        "market": snap,
        "name_count": len(rows),
        "max_names": MAX_NAMES,
        "too_many_names": len(rows) > MAX_NAMES,
        "generated_at": datetime.now(KST).replace(microsecond=0).isoformat(),
    }


def generate_opinion(kind: str = "opinion") -> dict:
    view = build_portfolio_view()
    kospi_pct = ((view.get("market") or {}).get("kospi") or {}).get("change_pct")
    regime, regime_note = _regime(kospi_pct)
    news = market.market_news()
    research = load_research() if kind == "opinion" else None
    tickets = _size_orders(view, regime, kospi_pct, kind)
    source = "rules"
    if research:
        tickets = _apply_research(tickets, view, research)
        source = "agent"
        if research.get("headline"):
            headline = research["headline"]
        else:
            headline = None
        if research.get("news"):
            news = research["news"]
        if research.get("regime_note"):
            regime_note = research["regime_note"]
    else:
        headline = None

    if not headline:
        if kind == "morning":
            headline = "장 시작 스냅샷입니다. 아래 보유 지시를 유지하고 11시 의견을 기다리세요."
        elif not tickets:
            headline = "등록된 보유 종목이 없습니다. 종목을 넣은 뒤 다시 의견을 받으세요."
        elif regime == "risk_off":
            headline = "오늘은 매수보다 생존입니다. 아래 문장만 그대로 실행하세요."
        else:
            headline = "아래 주문만 그대로 실행하고, 적혀 있지 않은 종목은 손대지 마세요."

    executable = [t for t in tickets if t["action"] in {"BUY", "SELL"} and t["shares"] > 0]
    payload = {
        "kind": kind,
        "source": source,
        "headline": headline,
        "regime": regime,
        "regime_note": regime_note,
        "kospi": (view.get("market") or {}).get("kospi"),
        "kosdaq": (view.get("market") or {}).get("kosdaq"),
        "news": news,
        "actions": tickets,
        "orders": executable,
        "max_names": MAX_NAMES,
        "cash": view.get("cash"),
        "disclaimer": (
            "이 문장은 실행용 지시입니다. 월 20%는 목표일 뿐 보장이 아닙니다. "
            "지정가가 호가와 안 맞으면 가장 가까운 호가로 넣고, 미체결 시 장 마감 전 취소하세요."
        ),
        "generated_at": datetime.now(KST).replace(microsecond=0).isoformat(),
    }
    saved = db.save_brief(kind, json.dumps(payload, ensure_ascii=False))
    payload["id"] = saved["id"]
    payload["day"] = saved["day"]
    return payload


def load_or_generate_today(kind: str, force: bool = False) -> dict:
    if not force:
        row = db.latest_brief(kind)
        if row:
            payload = json.loads(row["payload"])
            payload["id"] = row["id"]
            payload["day"] = row["day"]
            payload["created_at"] = row["created_at"]
            return payload
    return generate_opinion(kind)


def catch_up_if_needed() -> None:
    now = datetime.now(KST)
    if now.weekday() >= 5:
        return
    if now.hour >= 9 and not db.latest_brief("morning"):
        generate_opinion("morning")
    if now.hour >= 11 and not db.latest_brief("opinion"):
        generate_opinion("opinion")
