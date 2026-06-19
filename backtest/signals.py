from __future__ import annotations

import pandas as pd

from backtest.strategy import CrossType, attach_indicators, calc_ema, detect_cross_series

ema = calc_ema


def detect_signals(df: pd.DataFrame, fast: int = 20, slow: int = 200) -> pd.DataFrame:
    """EMAクロスシグナルを抽出する（strategy.pyへの委譲）。

    エントリーは「クロス確定の次の足の始値」（pf_spec.md準拠）。
    最終行でクロスした場合は次の足が無いため対象外とする。
    """
    data = attach_indicators(df, fast=fast, slow=slow, ma_type="ema")
    data["ema_fast"] = data["ma_fast"]
    data["ema_slow"] = data["ma_slow"]

    cross = detect_cross_series(data)
    cross_idx = data.index[cross != CrossType.NONE]

    signals = []
    for i in cross_idx:
        entry_idx = i + 1
        if entry_idx >= len(data):
            continue
        signals.append({
            "signal_date": data.loc[i, "time"],
            "signal_type": "GC" if cross.loc[i] == CrossType.GOLDEN else "DC",
            "entry_time": data.loc[entry_idx, "time"],
            "entry_price": data.loc[entry_idx, "open"],
            "entry_idx": entry_idx,
        })

    return pd.DataFrame(signals)
