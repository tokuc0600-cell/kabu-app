from __future__ import annotations

import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def detect_signals(df: pd.DataFrame, fast: int = 20, slow: int = 200) -> pd.DataFrame:
    """EMAクロスシグナルを抽出する。

    エントリーは「クロス確定の次の足の始値」（pf_spec.md準拠）。
    最終行でクロスした場合は次の足が無いため対象外とする。
    """
    data = df.copy()
    data["ema_fast"] = ema(data["close"], fast)
    data["ema_slow"] = ema(data["close"], slow)

    prev_fast = data["ema_fast"].shift(1)
    prev_slow = data["ema_slow"].shift(1)
    golden_cross = (prev_fast < prev_slow) & (data["ema_fast"] > data["ema_slow"])
    dead_cross = (prev_fast > prev_slow) & (data["ema_fast"] < data["ema_slow"])

    cross_idx = data.index[golden_cross | dead_cross]

    signals = []
    for i in cross_idx:
        entry_idx = i + 1
        if entry_idx >= len(data):
            continue
        signals.append({
            "signal_date": data.loc[i, "time"],
            "signal_type": "GC" if golden_cross.loc[i] else "DC",
            "entry_time": data.loc[entry_idx, "time"],
            "entry_price": data.loc[entry_idx, "open"],
            "entry_idx": entry_idx,
        })

    return pd.DataFrame(signals)
