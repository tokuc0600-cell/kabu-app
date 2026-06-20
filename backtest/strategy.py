from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd


def calc_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def calc_sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """RSI（表示専用の参考指標。エントリー/エグジット判定には使わない）。"""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_macd(
    series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD（表示専用の参考指標）。戻り値: (macd_line, signal_line, histogram)。"""
    ema_fast = calc_ema(series, fast)
    ema_slow = calc_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def attach_indicators(
    df: pd.DataFrame,
    fast: int,
    slow: int,
    ma_type: str = "ema",
    price_col: str = "close",
) -> pd.DataFrame:
    """df に ma_fast / ma_slow 列を追加して返す（FX=ema、株=sma想定）。"""
    calc = calc_ema if ma_type == "ema" else calc_sma
    data = df.copy()
    data["ma_fast"] = calc(data[price_col], fast)
    data["ma_slow"] = calc(data[price_col], slow)
    return data


class CrossType(Enum):
    NONE = "none"
    GOLDEN = "golden"
    DEAD = "dead"


def detect_cross_at(
    prev_fast: float, prev_slow: float, curr_fast: float, curr_slow: float
) -> CrossType:
    """直近1点だけのクロス判定（dashboard/syncのリアルタイム表示用）。"""
    if prev_fast <= prev_slow and curr_fast > curr_slow:
        return CrossType.GOLDEN
    if prev_fast >= prev_slow and curr_fast < curr_slow:
        return CrossType.DEAD
    return CrossType.NONE


def detect_cross_series(
    df: pd.DataFrame, fast_col: str = "ma_fast", slow_col: str = "ma_slow"
) -> pd.Series:
    """全行に対するクロス判定（backtest用）。CrossType値のSeriesを返す。"""
    prev_fast = df[fast_col].shift(1)
    prev_slow = df[slow_col].shift(1)
    curr_fast = df[fast_col]
    curr_slow = df[slow_col]

    golden = (prev_fast < prev_slow) & (curr_fast > curr_slow)
    dead = (prev_fast > prev_slow) & (curr_fast < curr_slow)

    cross = pd.Series(CrossType.NONE, index=df.index, dtype=object)
    cross[golden] = CrossType.GOLDEN
    cross[dead] = CrossType.DEAD
    return cross


class PositionState(Enum):
    NONE = "none"
    LONG = "long"


@dataclass
class Position:
    state: PositionState
    entry_price: float | None = None
    entry_time: pd.Timestamp | None = None


@dataclass
class StrategyParams:
    fast: int
    slow: int
    stop_loss_pct: float
    take_profit_pct: float
    ma_type: str = "ema"
    timeframe: str = "1d"


def should_enter(position: Position, cross: CrossType) -> bool:
    """エントリー条件：ノーポジ かつ ゴールデンクロス発生。"""
    return position.state == PositionState.NONE and cross == CrossType.GOLDEN


# 通知（scripts/check_exit_signals.py）用の全銘柄一律エグジット閾値。
# Sheetsの銘柄ごとの損切%・利確%（should_exit/step_positionが使う）とは別の、
# 通知専用のシンプルな一律ルールとして意図的に分離している。
STOP_LOSS_PCT = 5.0
TAKE_PROFIT_PCT = 10.0


def check_exit_by_pct(
    entry_price: float,
    current_price: float,
    stop_loss_pct: float = STOP_LOSS_PCT,
    take_profit_pct: float = TAKE_PROFIT_PCT,
) -> str | None:
    """保有開始価格からの%のみでエグジット判定（EMAクロスは見ない）。

    戻り値: "STOP_LOSS" / "TAKE_PROFIT" / None。
    同時に複数条件が成立した場合は保守的に損切りを優先する。
    """
    if stop_loss_pct and current_price <= entry_price * (1 - stop_loss_pct / 100):
        return "STOP_LOSS"
    if take_profit_pct and current_price >= entry_price * (1 + take_profit_pct / 100):
        return "TAKE_PROFIT"
    return None


def should_exit(
    position: Position,
    cross: CrossType,
    current_price: float,
    stop_loss_pct: float,
    take_profit_pct: float,
) -> tuple[bool, str | None]:
    """エグジット判定。戻り値: (exit_flag, exit_reason)。"""
    if position.state != PositionState.LONG or position.entry_price is None:
        return False, None

    reason = check_exit_by_pct(position.entry_price, current_price, stop_loss_pct, take_profit_pct)
    if reason:
        return True, reason
    if cross == CrossType.DEAD:
        return True, "DC"
    return False, None


def step_position(
    position: Position,
    cross: CrossType,
    current_price: float,
    current_time: pd.Timestamp,
    stop_loss_pct: float,
    take_profit_pct: float,
) -> tuple[Position, dict | None]:
    """現在の状態と最新の確定足情報から、次のポジション状態を返す。"""
    if position.state == PositionState.NONE:
        if should_enter(position, cross):
            new_position = Position(
                state=PositionState.LONG, entry_price=current_price, entry_time=current_time
            )
            return new_position, {"action": "ENTRY", "price": current_price, "time": current_time}
        return position, None

    exit_flag, reason = should_exit(position, cross, current_price, stop_loss_pct, take_profit_pct)
    if exit_flag:
        pnl_pct = (current_price - position.entry_price) / position.entry_price * 100
        new_position = Position(state=PositionState.NONE, entry_price=None, entry_time=None)
        return new_position, {
            "action": "EXIT",
            "reason": reason,
            "price": current_price,
            "time": current_time,
            "pnl_pct": round(pnl_pct, 4),
        }
    return position, None


def compute_latest_snapshot(
    df: pd.DataFrame, fast: int, slow: int, ma_type: str = "ema"
) -> dict:
    """直近の確定値（現在値・fast/slow値・乖離率・直近クロス）を返す表示専用関数。

    ポジション状態には関与しない。最低でも slow+1 本のデータが必要。
    """
    data = attach_indicators(df, fast, slow, ma_type=ma_type)
    curr = data.iloc[-1]
    prev = data.iloc[-2]

    cross = detect_cross_at(prev["ma_fast"], prev["ma_slow"], curr["ma_fast"], curr["ma_slow"])
    price = curr["close"]
    kairi_pct = (price - curr["ma_slow"]) / curr["ma_slow"] * 100
    trend = "上昇トレンド" if price > curr["ma_slow"] else "下降トレンド"

    if cross == CrossType.GOLDEN:
        signal_label = "買い"
    elif cross == CrossType.DEAD:
        signal_label = "売り"
    else:
        signal_label = "なし"

    return {
        "price": price,
        "fast": curr["ma_fast"],
        "slow": curr["ma_slow"],
        "kairi_pct": kairi_pct,
        "trend": trend,
        "cross": cross,
        "signal_label": signal_label,
    }
