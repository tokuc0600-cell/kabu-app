from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import gspread
import pandas as pd

from backtest.engine import print_summary, run, save_results

CREDENTIALS_PATH = Path(__file__).parent.parent / "credentials" / "my-project-stock-498414-56d26f2c27b1.json"

FX_DEFAULTS = {"timeframe": "4h", "fast": 20, "slow": 200}
STOCK_DEFAULTS = {"timeframe": "1d", "fast": 5, "slow": 25}


def _connect():
    gcp_json = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")
    if gcp_json:
        client = gspread.service_account_from_dict(json.loads(gcp_json))
    else:
        client = gspread.service_account(filename=str(CREDENTIALS_PATH))
    return client.open("kabu")


def _fx_tickers(spreadsheet) -> list[str]:
    records = spreadsheet.worksheet("FXウォッチリスト").get_all_records()
    return [t for t in (str(row.get("Yahooティッカー", "")).strip() for row in records) if t and t != "nan"]


def _stock_tickers(spreadsheet) -> list[str]:
    records = spreadsheet.worksheet("ウォッチリスト").get_all_records()
    return [f"{c}.T" for c in (str(row.get("銘柄コード", "")).strip() for row in records) if c and c != "nan"]


def run_batch(period: str = "2y", no_cache: bool = False) -> pd.DataFrame:
    spreadsheet = _connect()
    targets = [(t, FX_DEFAULTS) for t in _fx_tickers(spreadsheet)]
    targets += [(t, STOCK_DEFAULTS) for t in _stock_tickers(spreadsheet)]

    rows = []
    for ticker, params in targets:
        try:
            trades, summary = run(ticker, params["timeframe"], params["fast"], params["slow"], period, no_cache)
            detail_path = save_results(ticker, params["timeframe"], params["fast"], params["slow"], trades, summary)
            print_summary(ticker, params["timeframe"], params["fast"], params["slow"], summary, detail_path)
            rows.append({"ticker": ticker, "timeframe": params["timeframe"], **summary})
        except Exception as e:
            print(f"[エラー] {ticker}: {e}")

    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description="Google Sheetsの全ウォッチリスト対象に一括PFバックテストを実行する")
    parser.add_argument("--period", default="2y", help="取得期間（デフォルト: 2y）")
    parser.add_argument("--no-cache", action="store_true", help="キャッシュを無視して再取得")
    args = parser.parse_args()

    df = run_batch(period=args.period, no_cache=args.no_cache)
    print("\n=== 一括検証 完了 ===")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
