from __future__ import annotations

import argparse
from pathlib import Path
import pandas as pd

def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    required = ["time", "open", "high", "low", "close"]
    missing = [c for c in required if c not in cols]
    if missing:
        raise ValueError(f"CSVに必要列がありません: {missing}")
    out = df.rename(columns={cols[k]: k for k in cols})
    out["time"] = pd.to_datetime(out["time"], utc=True)
    out = out.sort_values("time").reset_index(drop=True)
    return out

def run_backtest(df: pd.DataFrame, fast: int = 20, slow: int = 200) -> tuple[pd.DataFrame, dict]:
    data = df.copy()
    data["ema_fast"] = ema(data["close"], fast)
    data["ema_slow"] = ema(data["close"], slow)
    data["signal"] = 0
    data.loc[data["ema_fast"] > data["ema_slow"], "signal"] = 1
    data["entry"] = (data["signal"] == 1) & (data["signal"].shift(1).fillna(0) == 0)
    data["exit"] = (data["signal"] == 0) & (data["signal"].shift(1).fillna(0) == 1)

    trades = []
    in_pos = False
    entry_price = None
    entry_time = None

    for _, row in data.iterrows():
        if (not in_pos) and row["entry"]:
            in_pos = True
            entry_price = row["close"]
            entry_time = row["time"]
        elif in_pos and row["exit"]:
            exit_price = row["close"]
            ret = (exit_price / entry_price) - 1
            trades.append({
                "entry_time": entry_time,
                "exit_time": row["time"],
                "entry_price": entry_price,
                "exit_price": exit_price,
                "return_pct": ret * 100
            })
            in_pos = False
            entry_price = None
            entry_time = None

    trades_df = pd.DataFrame(trades)
    summary = {
        "bars": len(data),
        "trades": len(trades_df),
        "win_rate_pct": round((trades_df["return_pct"] > 0).mean() * 100, 2) if len(trades_df) else 0.0,
        "avg_return_pct": round(trades_df["return_pct"].mean(), 4) if len(trades_df) else 0.0,
        "total_return_pct_simple_sum": round(trades_df["return_pct"].sum(), 4) if len(trades_df) else 0.0,
    }
    return trades_df, summary

def main():
    parser = argparse.ArgumentParser(description="4時間足CSVの簡易EMAクロス・バックテスト")
    parser.add_argument("csv_path", help="CSVファイルパス")
    parser.add_argument("--fast", type=int, default=20, help="短期EMA")
    parser.add_argument("--slow", type=int, default=200, help="長期EMA")
    parser.add_argument("--out", default="trades_output.csv", help="トレード出力CSV")
    args = parser.parse_args()

    df = load_csv(args.csv_path)
    trades_df, summary = run_backtest(df, fast=args.fast, slow=args.slow)
    trades_df.to_csv(args.out, index=False, encoding="utf-8-sig")

    print("=== Summary ===")
    for k, v in summary.items():
        print(f"{k}: {v}")
    print(f"saved: {Path(args.out).resolve()}")

if __name__ == "__main__":
    main()
