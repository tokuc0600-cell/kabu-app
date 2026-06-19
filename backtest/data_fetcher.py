from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

DATA_DIR = Path(__file__).parent / "data"


def _cache_path(ticker: str, timeframe: str) -> Path:
    return DATA_DIR / f"{ticker}_{timeframe}.csv"


def _is_cache_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    cached_date = datetime.fromtimestamp(path.stat().st_mtime).date()
    return cached_date == datetime.now().date()


def fetch_ohlcv(
    ticker: str,
    timeframe: str,
    period: str = "2y",
    no_cache: bool = False,
) -> pd.DataFrame:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = _cache_path(ticker, timeframe)

    if not no_cache and _is_cache_fresh(cache_path):
        df = pd.read_csv(cache_path)
        df["time"] = pd.to_datetime(df["time"], utc=True)
        return df

    hist = yf.Ticker(ticker).history(interval=timeframe, period=period)
    if hist.empty:
        raise ValueError(f"データを取得できませんでした: {ticker} ({timeframe})")

    df = hist.reset_index()
    df = df.rename(columns={df.columns[0]: "time"})
    df.columns = [str(c).lower() for c in df.columns]
    df = df[["time", "open", "high", "low", "close", "volume"]]
    df["time"] = pd.to_datetime(df["time"], utc=True)

    df.to_csv(cache_path, index=False, encoding="utf-8-sig")
    return df


def main():
    parser = argparse.ArgumentParser(description="yfinanceでOHLCVデータを取得・キャッシュする")
    parser.add_argument("--ticker", required=True, help="yfinanceティッカー（例: USDJPY=X / 7203.T）")
    parser.add_argument("--timeframe", required=True, choices=["1h", "4h", "1d"], help="時間足")
    parser.add_argument("--period", default="2y", help="取得期間（デフォルト: 2y）")
    parser.add_argument("--no-cache", action="store_true", help="キャッシュを無視して再取得")
    args = parser.parse_args()

    df = fetch_ohlcv(args.ticker, args.timeframe, period=args.period, no_cache=args.no_cache)
    print(f"取得件数: {len(df)}本")
    print(df.tail())


if __name__ == "__main__":
    main()
