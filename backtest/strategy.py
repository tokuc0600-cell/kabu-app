from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
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


def calc_stochastic(
    high: pd.Series, low: pd.Series, close: pd.Series,
    k_period: int = 14, d_period: int = 3, smooth_k: int = 3,
) -> tuple[pd.Series, pd.Series]:
    """ストキャスティクス・スロー（表示専用の参考指標）。戻り値: (%K, %D)。"""
    lowest_low = low.rolling(k_period).min()
    highest_high = high.rolling(k_period).max()
    raw_k = (close - lowest_low) / (highest_high - lowest_low) * 100
    k = raw_k.rolling(smooth_k).mean()
    d = k.rolling(d_period).mean()
    return k, d


def calc_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """ATR（Average True Range、Wilder方式。表示専用の参考指標）。"""
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def calc_adx(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """ADX（+DI, -DI, ADX。Wilder方式。表示専用の参考指標）。戻り値: (plus_di, minus_di, adx)。"""
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    atr = calc_atr(high, low, close, period)
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di) * 100
    adx = dx.ewm(alpha=1 / period, adjust=False).mean()
    return plus_di, minus_di, adx


def calc_cci(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20) -> pd.Series:
    """CCI（Commodity Channel Index。表示専用の参考指標）。"""
    typical_price = (high + low + close) / 3
    sma = typical_price.rolling(period).mean()
    mean_abs_dev = typical_price.rolling(period).apply(lambda x: (x - x.mean()).abs().mean(), raw=False)
    return (typical_price - sma) / (0.015 * mean_abs_dev)


def calc_williams_r(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Williams %R（表示専用の参考指標）。"""
    highest_high = high.rolling(period).max()
    lowest_low = low.rolling(period).min()
    return (highest_high - close) / (highest_high - lowest_low) * -100


def judge_indicator_signal(name: str, value, **params) -> str:
    """指標名と現在値から投資判断の参考表示（「買い」/「中立」/「売り」）を返す。

    investing.comの技術分析ページのような簡易サマリー表示用。あくまで参考表示であり、
    strategy.pyのエントリー/エグジット判定（EMAクロス・RCI）には使わない。
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"

    if name == "RSI":
        if value > 70:
            return "売り"
        if value < 30:
            return "買い"
        return "中立"
    if name == "Stochastic":
        if value > 80:
            return "売り"
        if value < 20:
            return "買い"
        return "中立"
    if name == "MACD":
        return "買い" if value > 0 else "売り" if value < 0 else "中立"
    if name == "ADX":
        plus_di, minus_di, adx = value
        if pd.isna(adx) or adx <= 25:
            return "中立"
        return "買い" if plus_di > minus_di else "売り"
    if name == "CCI":
        if value > 100:
            return "売り"
        if value < -100:
            return "買い"
        return "中立"
    if name == "WilliamsR":
        if value > -20:
            return "売り"
        if value < -80:
            return "買い"
        return "中立"
    if name == "RCI":
        if value >= RCI_OVERBOUGHT:
            return "売り"
        if value <= RCI_OVERSOLD:
            return "買い"
        return "中立"
    return "—"


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


RCI_PERIODS = {"short": 9, "mid": 26, "long": 52}
RCI_OVERSOLD = -80.0
RCI_OVERBOUGHT = 80.0


def calc_rci(series: pd.Series, period: int) -> pd.Series:
    """RCI（Rank Correlation Index・順位相関指数）。

    直近period本について、日付順位（直近=1〜最古=period）と価格順位（最高値=1〜最安値=period）の
    スピアマンの順位相関係数を-100〜+100で表す。
        RCI = (1 - 6 * Σd_i^2 / (n^3 - n)) * 100  （d_i = 日付順位_i - 価格順位_i, n = period）
    """
    def _rci(window: np.ndarray) -> float:
        n = len(window)
        date_rank = np.arange(n, 0, -1)
        price_rank = pd.Series(window).rank(ascending=False).to_numpy()
        d_sq_sum = np.sum((date_rank - price_rank) ** 2)
        return (1 - 6 * d_sq_sum / (n ** 3 - n)) * 100

    return series.rolling(period).apply(_rci, raw=True)


def attach_rci(
    df: pd.DataFrame, periods: dict[str, int] | None = None, price_col: str = "close"
) -> pd.DataFrame:
    """df に rci_short / rci_mid / rci_long 列を追加して返す。"""
    periods = periods or RCI_PERIODS
    data = df.copy()
    data["rci_short"] = calc_rci(data[price_col], periods["short"])
    data["rci_mid"] = calc_rci(data[price_col], periods["mid"])
    data["rci_long"] = calc_rci(data[price_col], periods["long"])
    return data


def detect_rci_signal_series(
    df: pd.DataFrame,
    short_col: str = "rci_short",
    oversold: float = RCI_OVERSOLD,
    overbought: float = RCI_OVERBOUGHT,
    *,
    direction: str = "long",
) -> pd.Series:
    """短期RCIの反転判定をCrossType形式で返す（既存のstep_position()をそのまま流用するため）。

    direction="long"（デフォルト）：
        GOLDEN：短期RCIが売られすぎ圏(oversold以下)から上向きに反転＝エントリー。
        DEAD　：短期RCIが買われすぎ圏(overbought以上)から下向きに反転＝エグジット。
    direction="short"：上記のエントリー/エグジット条件を入れ替える
        （買われすぎ圏からの反落＝エントリー、売られすぎ圏からの反発＝エグジット）。
    """
    prev = df[short_col].shift(1)
    curr = df[short_col]

    reversal_up = (prev <= oversold) & (curr > prev)
    reversal_down = (prev >= overbought) & (curr < prev)

    signal = pd.Series(CrossType.NONE, index=df.index, dtype=object)
    if direction == "short":
        signal[reversal_down] = CrossType.GOLDEN
        signal[reversal_up] = CrossType.DEAD
    else:
        signal[reversal_up] = CrossType.GOLDEN
        signal[reversal_down] = CrossType.DEAD
    return signal


def rci_formula_text(
    periods: dict[str, int] | None = None,
    oversold: float = RCI_OVERSOLD,
    overbought: float = RCI_OVERBOUGHT,
) -> str:
    """RCI（3line）の算出方法・判定ルールをUI表示用Markdownで返す。"""
    periods = periods or RCI_PERIODS
    return f"""
**RCI（Rank Correlation Index・順位相関指数）**

直近 n本について、「日付順位」（直近=1 〜 最古=n）と「価格順位」（最高値=1 〜 最安値=n）の
スピアマンの順位相関係数を -100〜+100 で表した指標。

```
RCI = (1 - 6 * Σd_i^2 / (n^3 - n)) * 100
d_i = 日付順位_i - 価格順位_i
```

- +100に近い：直近ほど高値が並ぶ＝強い上昇トレンド
- -100に近い：直近ほど安値が並ぶ＝強い下落トレンド

本ツールでは短期/中期/長期の3本（{periods['short']} / {periods['mid']} / {periods['long']}）を使用し、

- 短期線が **{oversold:.0f}以下から上向きに反転 → エントリー**
- 短期線が **{overbought:.0f}以上から下向きに反転 → エグジット**

と判定する（中期・長期線はトレンド確認の補助表示で、判定には使わない）。
"""


class PositionState(Enum):
    NONE = "none"
    LONG = "long"
    SHORT = "short"


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
    mode: str = "pct"
    stop_loss_pips: float = 0
    take_profit_pips: float = 0


def should_enter(position: Position, cross: CrossType, *, direction: str = "long") -> bool:
    """エントリー条件：ノーポジ かつ エントリー方向のクロス発生。

    direction="long"（デフォルト）：ゴールデンクロスでエントリー。
    direction="short"：デッドクロスでエントリー（株のショート対応用）。
    """
    if position.state != PositionState.NONE:
        return False
    entry_cross = CrossType.DEAD if direction == "short" else CrossType.GOLDEN
    return cross == entry_cross


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
    *,
    direction: str = "long",
) -> str | None:
    """保有開始価格からの%のみでエグジット判定（EMAクロスは見ない）。株専用。

    direction="long"（デフォルト）：下落で損切り、上昇で利確。
    direction="short"：上昇で損切り、下落で利確（不等号を反転）。
    戻り値: "STOP_LOSS" / "TAKE_PROFIT" / None。
    同時に複数条件が成立した場合は保守的に損切りを優先する。
    """
    if direction == "short":
        if stop_loss_pct and current_price >= entry_price * (1 + stop_loss_pct / 100):
            return "STOP_LOSS"
        if take_profit_pct and current_price <= entry_price * (1 - take_profit_pct / 100):
            return "TAKE_PROFIT"
        return None
    if stop_loss_pct and current_price <= entry_price * (1 - stop_loss_pct / 100):
        return "STOP_LOSS"
    if take_profit_pct and current_price >= entry_price * (1 + take_profit_pct / 100):
        return "TAKE_PROFIT"
    return None


def check_exit_by_pct_intrabar(
    entry_price: float,
    bar_high: float,
    bar_low: float,
    stop_loss_pct: float = 0,
    take_profit_pct: float = 0,
    *,
    direction: str = "long",
) -> tuple[str | None, float | None]:
    """1本のローソク足の高値・安値を使って、終値を待たずに損切り/利確ラインへの到達を判定する。

    終値だけで判定すると、ローソク足の値幅が閾値より大きい時間足（FXの1時間足など）で
    「設定した%より大きく損益が出る」結果になってしまう（実際の注文はラインに到達した時点で
    約定するため）。約定価格は閾値の価格そのもの（ラインに到達した時点）とする。
    同時に両方到達した場合は保守的に損切りを優先する。

    direction="long"（デフォルト）：下落で損切り、上昇で利確。
    direction="short"：上昇で損切り、下落で利確（株のショート対応用）。
    戻り値: (reason, exit_price) または到達なしの場合 (None, None)。
    """
    if direction == "short":
        if stop_loss_pct:
            sl_price = entry_price * (1 + stop_loss_pct / 100)
            if bar_high >= sl_price:
                return "STOP_LOSS", sl_price
        if take_profit_pct:
            tp_price = entry_price * (1 - take_profit_pct / 100)
            if bar_low <= tp_price:
                return "TAKE_PROFIT", tp_price
        return None, None
    if stop_loss_pct:
        sl_price = entry_price * (1 - stop_loss_pct / 100)
        if bar_low <= sl_price:
            return "STOP_LOSS", sl_price
    if take_profit_pct:
        tp_price = entry_price * (1 + take_profit_pct / 100)
        if bar_high >= tp_price:
            return "TAKE_PROFIT", tp_price
    return None, None


def check_exit_by_pips_intrabar(
    entry_price: float,
    bar_high: float,
    bar_low: float,
    stop_loss_pips: float,
    take_profit_pips: float,
    pip_multiplier: float,
) -> tuple[str | None, float | None]:
    """check_exit_by_pct_intrabar()のpips版（FX用）。"""
    if stop_loss_pips:
        sl_price = entry_price - stop_loss_pips / pip_multiplier
        if bar_low <= sl_price:
            return "STOP_LOSS", sl_price
    if take_profit_pips:
        tp_price = entry_price + take_profit_pips / pip_multiplier
        if bar_high >= tp_price:
            return "TAKE_PROFIT", tp_price
    return None, None


def pip_multiplier(ticker: str) -> float:
    """JPYペアは1pip=0.01のため×100、その他（EURUSD等）は1pip=0.0001のため×10000。"""
    return 100 if "JPY" in ticker else 10000


def check_exit_by_pips(
    entry_price: float,
    current_price: float,
    stop_loss_pips: float,
    take_profit_pips: float,
    pip_multiplier: float,
) -> str | None:
    """保有開始価格からのpips差のみでエグジット判定（EMAクロスは見ない）。FX専用。

    戻り値: "STOP_LOSS" / "TAKE_PROFIT" / None。
    同時に複数条件が成立した場合は保守的に損切りを優先する。
    """
    diff_pips = (current_price - entry_price) * pip_multiplier
    if stop_loss_pips and diff_pips <= -stop_loss_pips:
        return "STOP_LOSS"
    if take_profit_pips and diff_pips >= take_profit_pips:
        return "TAKE_PROFIT"
    return None


def should_exit(
    position: Position,
    cross: CrossType,
    current_price: float,
    stop_loss_pct: float = 0,
    take_profit_pct: float = 0,
    *,
    mode: str = "pct",
    stop_loss_pips: float = 0,
    take_profit_pips: float = 0,
    pip_multiplier_value: float = 10000,
    direction: str = "long",
) -> tuple[bool, str | None]:
    """エグジット判定。戻り値: (exit_flag, exit_reason)。

    mode="pct"（デフォルト・株用）はstop_loss_pct/take_profit_pctを使用。
    mode="pips"（FX用）はstop_loss_pips/take_profit_pips/pip_multiplier_valueを使用。
    direction="long"（デフォルト）はLONGポジション・デッドクロスでのエグジットを想定。
    direction="short"はSHORTポジション・ゴールデンクロスでのエグジットを想定（株専用）。
    """
    expected_state = PositionState.SHORT if direction == "short" else PositionState.LONG
    if position.state != expected_state or position.entry_price is None:
        return False, None

    if mode == "pips":
        reason = check_exit_by_pips(
            position.entry_price, current_price, stop_loss_pips, take_profit_pips, pip_multiplier_value
        )
    else:
        reason = check_exit_by_pct(
            position.entry_price, current_price, stop_loss_pct, take_profit_pct, direction=direction
        )
    if reason:
        return True, reason
    exit_cross = CrossType.GOLDEN if direction == "short" else CrossType.DEAD
    if cross == exit_cross:
        return True, "DC"
    return False, None


def step_position(
    position: Position,
    cross: CrossType,
    current_price: float,
    current_time: pd.Timestamp,
    stop_loss_pct: float = 0,
    take_profit_pct: float = 0,
    *,
    mode: str = "pct",
    stop_loss_pips: float = 0,
    take_profit_pips: float = 0,
    pip_multiplier_value: float = 10000,
    direction: str = "long",
) -> tuple[Position, dict | None]:
    """現在の状態と最新の確定足情報から、次のポジション状態を返す。

    mode="pct"（デフォルト・株用）/ "pips"（FX用）はshould_exit()に準拠。
    direction="long"（デフォルト）/ "short"（株専用）はエントリー方向の切り替え。
    """
    if position.state == PositionState.NONE:
        if should_enter(position, cross, direction=direction):
            new_state = PositionState.SHORT if direction == "short" else PositionState.LONG
            new_position = Position(state=new_state, entry_price=current_price, entry_time=current_time)
            return new_position, {
                "action": "ENTRY", "price": current_price, "time": current_time, "direction": direction,
            }
        return position, None

    exit_flag, reason = should_exit(
        position, cross, current_price, stop_loss_pct, take_profit_pct,
        mode=mode, stop_loss_pips=stop_loss_pips, take_profit_pips=take_profit_pips,
        pip_multiplier_value=pip_multiplier_value, direction=direction,
    )
    if exit_flag:
        if direction == "short":
            pnl_pct = (position.entry_price - current_price) / position.entry_price * 100
        else:
            pnl_pct = (current_price - position.entry_price) / position.entry_price * 100
        new_position = Position(state=PositionState.NONE, entry_price=None, entry_time=None)
        return new_position, {
            "action": "EXIT",
            "reason": reason,
            "price": current_price,
            "time": current_time,
            "pnl_pct": round(pnl_pct, 4),
            "direction": direction,
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
