import csv
import io
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Literal

from engine import Bar, WARMUP, replay, validate_bars


DB_PATH = Path(__file__).resolve().parent.parent / "data" / "tradelab.db"
DB_PATH.parent.mkdir(exist_ok=True)
app = FastAPI(title="Trade Lab")


@contextmanager
def database():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


with database() as connection:
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            kind TEXT NOT NULL,
            source TEXT NOT NULL,
            bars TEXT NOT NULL,
            cursor INTEGER NOT NULL,
            fee_rate REAL NOT NULL,
            slippage REAL NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS decisions (
            session_id TEXT NOT NULL,
            date TEXT NOT NULL,
            action TEXT NOT NULL,
            reason TEXT NOT NULL,
            PRIMARY KEY (session_id, date),
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );
    """)


class NewSession(BaseModel):
    symbol: str
    kind: Literal["stock", "etf"]
    source: Literal["akshare", "csv"] = "akshare"
    csv_text: str | None = None
    fee_rate: float = Field(default=0.001, ge=0, le=0.01, allow_inf_nan=False)
    slippage: float = Field(default=0.001, ge=0, le=0.01, allow_inf_nan=False)


class Decision(BaseModel):
    action: Literal["BUY", "SELL", "HOLD"]
    reason: str = Field(default="", max_length=500)


def parse_csv(text: str) -> list[Bar]:
    if len(text) > 1_000_000:
        raise ValueError("CSV 文件过大，最多支持 1 MB")
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    names = {"date": "日期", "open": "开盘", "high": "最高", "low": "最低", "close": "收盘", "volume": "成交量"}
    if not reader.fieldnames or any(english not in reader.fieldnames and chinese not in reader.fieldnames for english, chinese in names.items()):
        raise ValueError("CSV 需要 date,open,high,low,close,volume 六列（也支持对应中文列名）")
    bars = []
    for row in reader:
        values = {key: row.get(key, row.get(chinese)) for key, chinese in names.items()}
        try:
            day = date.fromisoformat(values["date"]).isoformat()
            bars.append(Bar(day, *(float(values[key]) for key in ("open", "high", "low", "close", "volume"))))
        except (TypeError, ValueError) as error:
            raise ValueError(f"第 {reader.line_num} 行数据无效") from error
    return bars


def fetch_akshare(symbol: str, kind: str) -> list[Bar]:
    try:
        import akshare as ak
    except ImportError as error:
        raise HTTPException(503, "未安装 AKShare，请先安装后端依赖，或导入 CSV") from error
    end = date.today()
    start = end - timedelta(days=600)
    try:
        if kind == "stock":
            frame = ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"), adjust="")
        else:
            frame = ak.fund_etf_hist_em(symbol=symbol, period="daily", start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"), adjust="")
        return [Bar(str(row["日期"])[:10], *(float(row[column]) for column in ("开盘", "最高", "最低", "收盘", "成交量"))) for _, row in frame.iterrows()]
    except Exception as error:
        raise HTTPException(502, f"AKShare 取数失败：{error}") from error


def session_row(session_id: str):
    with database() as connection:
        row = connection.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "实验不存在")
    return row


def session_view(row) -> dict:
    bars = [Bar(**item) for item in json.loads(row["bars"])]
    cursor = row["cursor"]
    with database() as connection:
        rows = connection.execute("SELECT date, action, reason FROM decisions WHERE session_id = ? ORDER BY date", (row["id"],)).fetchall()
    decisions = {item["date"]: item["action"] for item in rows}
    result = replay(bars, cursor, decisions, row["fee_rate"], row["slippage"])
    return {
        "id": row["id"], "symbol": row["symbol"], "kind": row["kind"], "source": row["source"],
        "created_at": row["created_at"], "fee_rate": row["fee_rate"], "slippage": row["slippage"],
        "date": bars[cursor].date, "step": cursor - WARMUP + 1, "total_steps": len(bars) - WARMUP,
        "finished": cursor == len(bars) - 1, "bars": [vars(item) for item in bars[max(0, cursor - 99):cursor + 1]],
        "decisions": [dict(item) for item in rows], **result,
    }


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/sessions")
def list_sessions():
    with database() as connection:
        rows = connection.execute("SELECT id, symbol, kind, source, created_at FROM sessions ORDER BY created_at DESC LIMIT 30").fetchall()
    return [dict(row) for row in rows]


@app.post("/api/sessions")
def create_session(request: NewSession):
    symbol = request.symbol.strip()
    if not re.fullmatch(r"\d{6}", symbol):
        raise HTTPException(422, "证券代码必须是 6 位数字")
    if request.source == "csv" and not request.csv_text:
        raise HTTPException(422, "请先选择 CSV 文件")
    try:
        bars = parse_csv(request.csv_text) if request.source == "csv" else fetch_akshare(symbol, request.kind)
        bars = bars[-260:]
        validate_bars(bars)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    session_id = uuid4().hex
    with database() as connection:
        connection.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (session_id, symbol, request.kind, request.source, json.dumps([vars(bar) for bar in bars]), WARMUP - 1,
             request.fee_rate, request.slippage, datetime.now().isoformat(timespec="seconds")),
        )
    return session_view(session_row(session_id))


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    return session_view(session_row(session_id))


@app.post("/api/sessions/{session_id}/step")
def step_session(session_id: str, decision: Decision):
    if decision.action != "HOLD" and not decision.reason.strip():
        raise HTTPException(422, "买入或卖出必须填写决策理由")
    with database() as connection:
        row = connection.execute("SELECT bars, cursor FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "实验不存在")
        bars = json.loads(row["bars"])
        if row["cursor"] >= len(bars) - 1:
            raise HTTPException(409, "实验已经结束")
        current_date = bars[row["cursor"]]["date"]
        connection.execute("INSERT INTO decisions VALUES (?, ?, ?, ?)", (session_id, current_date, decision.action, decision.reason.strip()))
        connection.execute("UPDATE sessions SET cursor = cursor + 1 WHERE id = ?", (session_id,))
    return session_view(session_row(session_id))
