from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from math import isfinite


WARMUP = 20
CENT = Decimal("0.01")
INITIAL_CASH = Decimal("100000.00")


@dataclass(frozen=True)
class Bar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Account:
    cash: Decimal = INITIAL_CASH
    shares: int = 0
    trades: list[dict] = field(default_factory=list)

    def equity(self, close: float) -> float:
        return float((self.cash + self.shares * Decimal(str(close))).quantize(CENT, rounding=ROUND_HALF_UP))


def signal(bars: list[Bar], index: int) -> str:
    average = sum(bar.close for bar in bars[index - WARMUP + 1 : index + 1]) / WARMUP
    return "BUY" if bars[index].close > average else "SELL"


def fill(account: Account, action: str, bar: Bar, fee_rate: float, slippage: float) -> None:
    if action == "HOLD" or bar.volume <= 0:
        return
    fee = Decimal(str(fee_rate))
    slip = Decimal(str(slippage))
    if action == "BUY" and account.shares == 0:
        price = Decimal(str(bar.open)) * (1 + slip)
        shares = int(account.cash / (price * (1 + fee)) / 100) * 100
        while shares > 0:
            gross = (price * shares).quantize(CENT, rounding=ROUND_HALF_UP)
            commission = (gross * fee).quantize(CENT, rounding=ROUND_HALF_UP)
            if gross + commission <= account.cash:
                break
            shares -= 100
        if shares <= 0:
            return
        account.cash -= gross + commission
    elif action == "SELL" and account.shares > 0:
        price = Decimal(str(bar.open)) * (1 - slip)
        shares = account.shares
        gross = (price * shares).quantize(CENT, rounding=ROUND_HALF_UP)
        commission = (gross * fee).quantize(CENT, rounding=ROUND_HALF_UP)
        account.cash += gross - commission
        shares = -shares
    else:
        return
    account.shares += shares
    account.trades.append({"date": bar.date, "action": action, "shares": abs(shares), "price": float(round(price, 4))})


def replay(bars: list[Bar], cursor: int, decisions: dict[str, str], fee_rate: float, slippage: float) -> dict:
    manual, rule, benchmark = Account(), Account(), Account()
    curves = [{"date": bars[WARMUP - 1].date, "manual": float(INITIAL_CASH), "rule": float(INITIAL_CASH), "benchmark": float(INITIAL_CASH)}]
    for day in range(WARMUP, cursor + 1):
        previous = bars[day - 1]
        fill(manual, decisions.get(previous.date, "HOLD"), bars[day], fee_rate, slippage)
        fill(rule, signal(bars, day - 1), bars[day], fee_rate, slippage)
        fill(benchmark, "BUY" if day == WARMUP else "HOLD", bars[day], fee_rate, slippage)
        curves.append({"date": bars[day].date, "manual": manual.equity(bars[day].close), "rule": rule.equity(bars[day].close), "benchmark": benchmark.equity(bars[day].close)})
    return {
        "accounts": {
            name: {"cash": float(account.cash), "shares": account.shares, "equity": account.equity(bars[cursor].close), "trades": account.trades}
            for name, account in (("manual", manual), ("rule", rule), ("benchmark", benchmark))
        },
        "curves": curves,
        "signal": signal(bars, cursor),
    }


def validate_bars(bars: list[Bar]) -> None:
    if len(bars) <= WARMUP:
        raise ValueError(f"至少需要 {WARMUP + 1} 个交易日的数据")
    dates = [bar.date for bar in bars]
    if dates != sorted(set(dates)):
        raise ValueError("交易日期必须唯一且升序")
    for bar in bars:
        prices = (bar.open, bar.high, bar.low, bar.close)
        if not all(isfinite(price) and price > 0 for price in prices):
            raise ValueError(f"{bar.date} 的价格无效")
        if bar.low > min(bar.open, bar.close) or bar.high < max(bar.open, bar.close) or bar.low > bar.high:
            raise ValueError(f"{bar.date} 的最高价或最低价无效")
        if not isfinite(bar.volume) or bar.volume < 0:
            raise ValueError(f"{bar.date} 的成交量无效")
