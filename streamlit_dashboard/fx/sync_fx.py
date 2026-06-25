import gspread
import yfinance as yf
import time
import pandas as pd
import os
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backtest.strategy import (
    Position,
    PositionState,
    attach_indicators,
    detect_cross_at,
    pip_multiplier,
    step_position,
)

FAST, SLOW = 20, 200

EXIT_SIGNAL_LABELS = {
    "DC": "▼デッドクロス（売り）",
    "STOP_LOSS": "■損切り",
    "TAKE_PROFIT": "●利確",
}

EXIT_SIGNAL_LABELS_SHORT = {
    "DC": "▲ゴールデンクロス（買い戻し注意）",
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


def _resolve_direction(row: dict) -> str:
    """Sheetsの「売買方向」列から取引方向を判定する（空欄・列が無い場合は"long"扱いで後方互換）。"""
    return "short" if str(row.get("売買方向", "")).strip() == "ショート" else "long"


def _build_position(row: dict, direction: str) -> Position:
    expected_label = "ショート中" if direction == "short" else "ロング中"
    expected_state = PositionState.SHORT if direction == "short" else PositionState.LONG
    state = expected_state if row.get("ポジション状態") == expected_label else PositionState.NONE
    entry_price = row.get("建値")
    entry_price = float(entry_price) if entry_price not in (None, "", "nan") else None
    return Position(state=state, entry_price=entry_price)


def _to_pips(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def compute_pair_update(ticker_code: str, row: dict) -> dict | None:
    """1通貨ペアの最新シグナル・ポジション更新内容を計算する（strategy.py一元ロジック）。"""
    hist = yf.Ticker(ticker_code).history(interval="4h", period="60d")
    if len(hist) < SLOW + 1:
        return None

    df = attach_indicators(_to_ohlc_df(hist), fast=FAST, slow=SLOW, ma_type="ema")
    curr, prev = df.iloc[-1], df.iloc[-2]

    current_price = round(curr["close"], 3)
    ema_fast = round(curr["ma_fast"], 3)
    ema_slow = round(curr["ma_slow"], 3)
    kairi = round((current_price - ema_fast) / ema_fast * 100, 2)

    if current_price > ema_fast > ema_slow:
        trend = "強い上昇"
    elif current_price < ema_fast < ema_slow:
        trend = "強い下降"
    elif current_price > ema_fast:
        trend = "やや上昇"
    else:
        trend = "やや下降"

    cross = detect_cross_at(prev["ma_fast"], prev["ma_slow"], curr["ma_fast"], curr["ma_slow"])

    direction = _resolve_direction(row)
    position = _build_position(row, direction)
    stop_loss_pips = _to_pips(row.get("損切りpips"))
    take_profit_pips = _to_pips(row.get("利確pips"))
    new_position, event = step_position(
        position, cross, current_price, curr["time"],
        mode="pips", stop_loss_pips=stop_loss_pips, take_profit_pips=take_profit_pips,
        pip_multiplier_value=pip_multiplier(ticker_code), direction=direction,
    )

    if event and event["action"] == "ENTRY":
        signal = "★デッドクロス（ショートサイン）" if direction == "short" else "★ゴールデンクロス（買い）"
    elif event and event["action"] == "EXIT":
        labels = EXIT_SIGNAL_LABELS_SHORT if direction == "short" else EXIT_SIGNAL_LABELS
        signal = labels.get(event["reason"], "安定")
    else:
        signal = "安定"

    position_state = "ノーポジ"
    if new_position.state == PositionState.LONG:
        position_state = "ロング中"
    elif new_position.state == PositionState.SHORT:
        position_state = "ショート中"

    return {
        "current_price": current_price,
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "kairi_pct": kairi,
        "trend": trend,
        "signal": signal,
        "entry_price": new_position.entry_price if new_position.entry_price is not None else "",
        "position_state": position_state,
    }


def update_fx_watchlist_with_signals(sheet=None, spreadsheet=None, target_pairs=None):
    """FXウォッチリストの全銘柄（またはtarget_pairsで絞った銘柄）を更新する。

    target_pairs を指定すると、その通貨ペア名のみを更新する（API呼び出し削減用）。
    """
    print("\n--- 【FXウォッチリスト】のテクニカル分析＆自動更新を開始します ---")
    if sheet is None:
        spreadsheet = spreadsheet or _connect()
        try:
            sheet = spreadsheet.worksheet("FXウォッチリスト")
        except Exception as e:
            print(f"タブ【FXウォッチリスト】が見つかりません: {e}")
            return

    records = sheet.get_all_records()
    all_updates = []

    print("--- フェーズ1: データ取得 ---")
    for idx, row in enumerate(records, start=2):
        ticker_code = str(row.get("Yahooティッカー", "")).strip()
        pair_name = str(row.get("通貨ペア名", "")).strip()

        if not ticker_code or ticker_code == "nan":
            continue
        if target_pairs is not None and pair_name not in target_pairs:
            continue

        try:
            result = compute_pair_update(ticker_code, row)
            if result is None:
                print(f"[警告] {ticker_code} データ不足（200本未満）")
                continue

            updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            all_updates.append({
                "row": idx,
                "values": [
                    result["current_price"], result["ema_fast"], result["ema_slow"],
                    f"{result['kairi_pct']}%", result["trend"], result["signal"], updated_at,
                    result["entry_price"], result["position_state"],
                ],
                "label": f"{pair_name} ({ticker_code})",
            })
            print(f"[取得] {pair_name} ({ticker_code}) 現在値:{result['current_price']}")
        except Exception as e:
            print(f"[エラー] {ticker_code}: {e}")

        time.sleep(1.2)

    print(f"\n--- フェーズ2: {len(all_updates)}銘柄を書き込み中 ---")
    for item in all_updates:
        row = item["row"]
        vals = item["values"]
        # C-I（現在値〜最終更新日時）とL-M（建値・ポジション状態）をそれぞれ1回のbatch_updateで書き込む
        # （セルごとのupdate_cellは429クォータエラーの原因になるため避ける）
        sheet.batch_update([
            {"range": f"C{row}:I{row}", "values": [vals[:7]]},
            {"range": f"L{row}:M{row}", "values": [vals[7:]]},
        ])
        time.sleep(1.2)
        print(f"[書き込み完了] {item['label']}")


if __name__ == "__main__":
    update_fx_watchlist_with_signals()
    print("\nすべてのFXテクニカル指標の同期が完了しました！")
