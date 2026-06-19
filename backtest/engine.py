from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

from backtest.data_fetcher import fetch_ohlcv
from backtest.signals import detect_signals

RESULTS_DIR = Path(__file__).parent / "results"


def _is_fx(ticker: str) -> bool:
    return "=X" in ticker


def _pip_multiplier(ticker: str) -> float:
    """JPYペアは1pip=0.01のため×100、その他（EURUSD等）は1pip=0.0001のため×10000。"""
    return 100 if "JPY" in ticker else 10000


def build_trades(signals: pd.DataFrame, is_fx: bool, pip_multiplier: float = 10000) -> pd.DataFrame:
    """連続するシグナルをペアにしてトレードを構築する。

    シグナルiでポジションを開き、次のシグナル(i+1)のentryで決済する
    （ホールド型・次のクロスでイグジット）。最後のシグナルは未決済のため対象外。
    """
    trades = []
    for i in range(len(signals) - 1):
        entry = signals.iloc[i]
        exit_ = signals.iloc[i + 1]
        direction = 1 if entry["signal_type"] == "GC" else -1

        if is_fx:
            profit_loss = (exit_["entry_price"] - entry["entry_price"]) * direction * pip_multiplier
        else:
            profit_loss = (exit_["entry_price"] - entry["entry_price"]) / entry["entry_price"] * direction * 100

        trades.append({
            "signal_date": entry["signal_date"],
            "signal_type": entry["signal_type"],
            "entry_price": entry["entry_price"],
            "exit_price": exit_["entry_price"],
            "profit_loss": round(profit_loss, 4),
            "result": "WIN" if profit_loss > 0 else "LOSS",
            "hold_bars": int(exit_["entry_idx"] - entry["entry_idx"]),
        })

    return pd.DataFrame(trades)


def summarize(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "avg_profit": 0.0,
            "avg_loss": 0.0,
            "risk_reward": 0.0,
            "max_drawdown": 0.0,
        }

    wins = trades.loc[trades["profit_loss"] > 0, "profit_loss"]
    losses = trades.loc[trades["profit_loss"] < 0, "profit_loss"]

    total_profit = wins.sum()
    total_loss = abs(losses.sum())

    equity_curve = trades["profit_loss"].cumsum()
    running_max = equity_curve.cummax()
    drawdown = running_max - equity_curve
    max_drawdown = drawdown.max() if not drawdown.empty else 0.0

    avg_profit = wins.mean() if len(wins) else 0.0
    avg_loss = abs(losses.mean()) if len(losses) else 0.0

    return {
        "total_trades": len(trades),
        "win_rate": round((trades["result"] == "WIN").mean() * 100, 2),
        "profit_factor": round(total_profit / total_loss, 2) if total_loss else float("inf"),
        "avg_profit": round(avg_profit, 4),
        "avg_loss": round(avg_loss, 4),
        "risk_reward": round(avg_profit / avg_loss, 2) if avg_loss else float("inf"),
        "max_drawdown": round(max_drawdown, 4),
    }


def run(ticker: str, timeframe: str, fast: int, slow: int, period: str, no_cache: bool) -> tuple[pd.DataFrame, dict]:
    df = fetch_ohlcv(ticker, timeframe, period=period, no_cache=no_cache)
    signals = detect_signals(df, fast=fast, slow=slow)
    trades = build_trades(signals, is_fx=_is_fx(ticker), pip_multiplier=_pip_multiplier(ticker))
    summary = summarize(trades)
    return trades, summary


def save_results(ticker: str, timeframe: str, fast: int, slow: int, trades: pd.DataFrame, summary: dict) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")

    detail_path = RESULTS_DIR / f"{today}_{ticker}_{timeframe}_fast{fast}_slow{slow}.csv"
    trades.to_csv(detail_path, index=False, encoding="utf-8-sig")

    summary_path = RESULTS_DIR / f"{today}_summary.csv"
    summary_row = pd.DataFrame([{
        "ticker": ticker,
        "timeframe": timeframe,
        "fast_ema": fast,
        "slow_ema": slow,
        **summary,
    }])
    if summary_path.exists():
        summary_row.to_csv(summary_path, mode="a", header=False, index=False, encoding="utf-8-sig")
    else:
        summary_row.to_csv(summary_path, index=False, encoding="utf-8-sig")

    return detail_path


def print_summary(ticker: str, timeframe: str, fast: int, slow: int, summary: dict, detail_path: Path) -> None:
    unit = "pips" if _is_fx(ticker) else "%"
    print("=" * 40)
    print(f"バックテスト結果: {ticker} {timeframe} EMA{fast}/{slow}")
    print("=" * 40)
    print(f"総トレード数    : {summary['total_trades']}")
    print(f"勝率            : {summary['win_rate']}%")
    print(f"プロフィットファクター: {summary['profit_factor']}")
    print(f"平均利益        : {summary['avg_profit']} {unit}")
    print(f"平均損失        : {summary['avg_loss']} {unit}")
    print(f"リスクリワード比: {summary['risk_reward']}")
    print(f"最大ドローダウン: {summary['max_drawdown']} {unit}")
    print("=" * 40)
    print(f"結果保存: {detail_path}")


def main():
    parser = argparse.ArgumentParser(description="EMAクロスシグナルのPFバックテストエンジン")
    parser.add_argument("--ticker", required=True, help="yfinanceティッカー（FX例: USDJPY=X / 株例: 7203.T）")
    parser.add_argument("--timeframe", required=True, choices=["1h", "4h", "1d"], help="時間足")
    parser.add_argument("--fast", type=int, default=20, help="fastEMA期間")
    parser.add_argument("--slow", type=int, default=200, help="slowEMA期間")
    parser.add_argument("--period", default="2y", help="取得期間（デフォルト: 2y）")
    parser.add_argument("--no-cache", action="store_true", help="キャッシュを無視して再取得")
    args = parser.parse_args()

    trades, summary = run(args.ticker, args.timeframe, args.fast, args.slow, args.period, args.no_cache)
    detail_path = save_results(args.ticker, args.timeframe, args.fast, args.slow, trades, summary)
    print_summary(args.ticker, args.timeframe, args.fast, args.slow, summary, detail_path)


if __name__ == "__main__":
    main()
