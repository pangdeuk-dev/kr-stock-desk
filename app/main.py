from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import db, market, opinions, scheduler

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

app = FastAPI(title="KR Stock Desk")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class HoldingIn(BaseModel):
    ticker: str = Field(min_length=1)
    qty: float = Field(gt=0)
    avg_price: float = Field(gt=0)
    memo: str = ""
    name: str = ""


class CashIn(BaseModel):
    cash: float = Field(ge=0)


class MonthStartIn(BaseModel):
    month_start_equity: float = Field(ge=0)


class JournalIn(BaseModel):
    body: str = Field(min_length=1)


@app.on_event("startup")
def on_startup() -> None:
    db.init_db()
    scheduler.start()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/portfolio")
def api_portfolio() -> dict:
    return opinions.build_portfolio_view()


@app.get("/api/search")
def api_search(q: str = "") -> dict:
    return {"items": market.search_stocks(q)}


@app.post("/api/holdings")
def api_add_holding(body: HoldingIn) -> dict:
    ticker = body.ticker.strip()
    if ticker.isdigit():
        ticker = ticker.zfill(6)
    try:
        q = market.quote(ticker)
    except Exception as exc:
        raise HTTPException(400, f"종목 시세를 찾지 못했습니다: {exc}") from exc
    name = body.name.strip() or q["name"]
    count = len(db.list_holdings())
    exists = any(h["ticker"] == q["ticker"] for h in db.list_holdings())
    if not exists and count >= 6:
        raise HTTPException(400, "종목이 6개를 넘습니다. 하나를 정리한 뒤 추가하세요.")
    holding = db.upsert_holding(q["ticker"], name, body.qty, body.avg_price, body.memo)
    return {"holding": holding}


@app.delete("/api/holdings/{holding_id}")
def api_delete_holding(holding_id: int) -> dict:
    db.delete_holding(holding_id)
    return {"ok": True}


@app.post("/api/settings/cash")
def api_cash(body: CashIn) -> dict:
    db.set_setting("cash", str(body.cash))
    return {"cash": body.cash}


@app.post("/api/settings/month-start")
def api_month_start(body: MonthStartIn) -> dict:
    db.set_setting("month_start_equity", str(body.month_start_equity))
    db.set_setting("month_key", db.month_key())
    return {"month_start_equity": body.month_start_equity}


@app.get("/api/journal")
def api_journal_list() -> dict:
    return {"items": db.list_journal()}


@app.post("/api/journal")
def api_journal_add(body: JournalIn) -> dict:
    return db.add_journal(body.body)


def _brief_out(row: dict | None) -> dict | None:
    if not row:
        return None
    payload = json.loads(row["payload"])
    payload["id"] = row["id"]
    payload["day"] = row["day"]
    payload["created_at"] = row["created_at"]
    return payload


@app.get("/api/opinions")
def api_opinions() -> dict:
    return {
        "morning": _brief_out(db.latest_brief("morning")),
        "opinion": _brief_out(db.latest_brief("opinion")),
    }


@app.post("/api/opinions/generate")
def api_generate(kind: str = "opinion") -> dict:
    if kind not in {"opinion", "morning"}:
        raise HTTPException(400, "kind must be opinion or morning")
    return opinions.generate_opinion(kind)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
