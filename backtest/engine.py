from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

from backtest.data_fetcher import fetch_ohlcv
from backtest.strategy import (
    Position,
    PositionState,
    attach_indicators,
    detect_cross_series,
    pip_multiplier as _pip_multiplier,
    step_position,
)

RESULTS_DIR = Path(__file__).parent / "results"


def _is_fx(ticker: str) -> bool:
    return "=X" in ticker


def to_engine_df(df_chart: pd.DataFrame) -> pd.DataFrame:
    """yfinance形式（Open/High/Low/Close/Volume・DatetimeIndex）を、
    build_trades()が期待する小文字OHLC列（time, open, high, low, close, volume）に変換する。
    株・FX両方のStreamlit画面から共通で呼べるユーティリティ。
    """
    data = df_chart.reset_index()
    data = data.rename(columns={data.columns[0]: "time"})
    data.columns = [str(c).lower() for c in data.columns]
    return data[["time", "open", "high", "low", "close", "volume"]]


def build_trades(
    df: pd.DataFrame,
    fast: int,
    slow: int,
    stop_loss_pct: float,
    take_profit_pct: float,
    is_fx: bool,
    pip_multiplier: float = 10000,
    ma_type: str = "ema",
) -> pd.DataFrame:
    """strategy.step_position()で1本ずつポジション状態を遷移させてトレードを構築する。

    エントリー：ゴールデンクロス（確定足）かつノーポジ。
    エグジット：デッドクロス or 損切りライン or 利確ラインのいずれか（strategy.should_exit準拠）。
    """
    data = attach_indicators(df, fast=fast, slow=slow, ma_type=ma_type)
    cross = detect_cross_series(data)

    position = Position(state=PositionState.NONE)
    pending_entry = None
    trades = []

    for i in range(1, len(data)):
        current_price = data["close"].iloc[i]
        current_time = data["time"].iloc[i]
        position, event = step_position(
            position,
            cross.iloc[i],
            current_price,
            current_time,
            stop_loss_pct,
            take_profit_pct,
        )
        if event is None:
            continue

        if event["action"] == "ENTRY":
            pending_entry = {**event, "idx": i}
        elif event["action"] == "EXIT" and pending_entry is not None:
            profit_loss = (
                (event["price"] - pending_entry["price"]) * pip_multiplier
                if is_fx
                else (event["price"] - pending_entry["price"]) / pending_entry["price"] * 100
            )

            trades.append({
                "signal_date": pending_entry["time"],
                "exit_date": event["time"],
                "signal_type": "GC",
                "entry_price": pending_entry["price"],
                "exit_price": event["price"],
                "profit_loss": round(profit_loss, 4),
                "result": "WIN" if profit_loss > 0 else "LOSS",
                "hold_bars": i - pending_entry["idx"],
                "exit_reason": event["reason"],
            })
            pending_entry = None

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


def run(
    ticker: str,
    timeframe: str,
    fast: int,
    slow: int,
    period: str,
    no_cache: bool,
    stop_loss_pct: float = 0.0,
    take_profit_pct: float = 0.0,
) -> tuple[pd.DataFrame, dict]:
    df = fetch_ohlcv(ticker, timeframe, period=period, no_cache=no_cache)
    trades = build_trades(
        df,
        fast=fast,
        slow=slow,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        is_fx=_is_fx(ticker),
        pip_multiplier=_pip_multiplier(ticker),
    )
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
    parser.add_argument("--stop-loss", type=float, default=0.0, help="損切りライン（建値からの下落率%、0=無効）")
    parser.add_argument("--take-profit", type=float, default=0.0, help="利確ライン（建値からの上昇率%、0=無効）")
    args = parser.parse_args()

    trades, summary = run(
        args.ticker,
        args.timeframe,
        args.fast,
        args.slow,
        args.period,
        args.no_cache,
        stop_loss_pct=args.stop_loss,
        take_profit_pct=args.take_profit,
    )
    detail_path = save_results(args.ticker, args.timeframe, args.fast, args.slow, trades, summary)
    print_summary(args.ticker, args.timeframe, args.fast, args.slow, summary, detail_path)


if __name__ == "__main__":
    main()
