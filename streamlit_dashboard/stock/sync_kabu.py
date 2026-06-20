import gspread
import yfinance as yf
import time
import pandas as pd
import os
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backtest.strategy import (
    Position,
    PositionState,
    attach_indicators,
    detect_cross_at,
    step_position,
)

FAST, SLOW = 5, 25

EXIT_SIGNAL_LABELS = {
    "DC": "▼デッドクロス（売り注意）",
    "STOP_LOSS": "■損切り",
    "TAKE_PROFIT": "●利確",
}


def _connect():
    gcp_json = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")
    if gcp_json:
        client = gspread.service_account_from_dict(json.loads(gcp_json))
    else:
        client = gspread.service_account(filename="../../credentials/my-project-stock-498414-56d26f2c27b1.json")
    return client.open("kabu")


def _to_ohlc_df(hist: pd.DataFrame) -> pd.DataFrame:
    df = hist.reset_index()
    df = df.rename(columns={df.columns[0]: "time"})
    df.columns = [str(c).lower() for c in df.columns]
    return df[["time", "open", "high", "low", "close", "volume"]]


def _build_position(row: dict) -> Position:
    state = PositionState.LONG if row.get("ポジション状態") == "ロング中" else PositionState.NONE
    entry_price = row.get("建値")
    entry_price = float(entry_price) if entry_price not in (None, "", "nan") else None
    return Position(state=state, entry_price=entry_price)


def _to_pct(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def compute_stock_update(ticker_code: str, row: dict) -> dict | None:
    """1銘柄の最新シグナル・ポジション更新内容を計算する（strategy.py一元ロジック）。"""
    hist = yf.Ticker(ticker_code).history(period="6mo")
    if len(hist) < SLOW + 1:
        return None

    df = attach_indicators(_to_ohlc_df(hist), fast=FAST, slow=SLOW, ma_type="sma")
    curr, prev = df.iloc[-1], df.iloc[-2]

    current_price = round(curr["close"], 2)
    ma25_value = round(curr["ma_slow"], 2)
    kairi = round((current_price - ma25_value) / ma25_value * 100, 2)

    cross = detect_cross_at(prev["ma_fast"], prev["ma_slow"], curr["ma_fast"], curr["ma_slow"])

    position = _build_position(row)
    stop_loss_pct = _to_pct(row.get("損切り%"))
    take_profit_pct = _to_pct(row.get("利確%"))
    new_position, event = step_position(
        position, cross, current_price, curr["time"], stop_loss_pct, take_profit_pct
    )

    if event and event["action"] == "ENTRY":
        signal = "★ゴールデンクロス（買いサイン）"
    elif event and event["action"] == "EXIT":
        signal = EXIT_SIGNAL_LABELS.get(event["reason"], "安定")
    elif current_price > ma25_value:
        signal = "上昇トレンド"
    else:
        signal = "下降トレンド"

    return {
        "current_price": current_price,
        "ma25_value": ma25_value,
        "kairi_pct": kairi,
        "signal": signal,
        "entry_price": new_position.entry_price if new_position.entry_price is not None else "",
        "position_state": "ロング中" if new_position.state == PositionState.LONG else "ノーポジ",
    }


def update_watchlist_with_signals(sheet=None, spreadsheet=None, target_codes=None):
    """ウォッチリストの全銘柄（またはtarget_codesで絞った銘柄）を更新する。"""
    print("\n--- 【ウォッチリスト】のテクニカル分析＆自動更新を開始します ---")
    if sheet is None:
        spreadsheet = spreadsheet or _connect()
        try:
            sheet = spreadsheet.worksheet("ウォッチリスト")
        except Exception as e:
            print(f"タブ【ウォッチリスト】が見つかりません: {e}")
            return

    records = sheet.get_all_records()

    for idx, row in enumerate(records, start=2):
        code = str(row.get("銘柄コード", "")).strip()
        if not code or code == "nan":
            continue
        if target_codes is not None and code not in target_codes:
            continue

        ticker_code = f"{code}.T"
        try:
            result = compute_stock_update(ticker_code, row)
            if result is None:
                print(f"[警告] {code} のデータ数が足りません（25日未満）。")
                continue

            # D:現在値, E:25日移動平均, F:25日乖離率, G:シグナル, J:建値, K:ポジション状態
            sheet.batch_update([
                {
                    "range": f"D{idx}:G{idx}",
                    "values": [[result["current_price"], result["ma25_value"], f"{result['kairi_pct']}%", result["signal"]]],
                },
                {
                    "range": f"J{idx}:K{idx}",
                    "values": [[result["entry_price"], result["position_state"]]],
                },
            ])

            print(
                f"[成功] {row.get('銘柄名', code)} ({code}) -> "
                f"現在値:{result['current_price']}円 | 25日線:{result['ma25_value']}円 | "
                f"乖離率:{result['kairi_pct']}% | 状態:{result['signal']}"
            )
        except Exception as e:
            print(f"[エラー] {code} の解析中に問題発生: {e}")

        time.sleep(1.2)


if __name__ == "__main__":
    update_watchlist_with_signals()
    print("\nすべてのテクニカル指標の同期が完了しました！")
