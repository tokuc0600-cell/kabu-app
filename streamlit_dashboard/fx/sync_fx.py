import gspread
import yfinance as yf
import time
import requests
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
    attach_rci,
    detect_rci_signal_series,
    pip_multiplier,
    step_position,
    RCI_PERIODS,
)

FAST, SLOW = 20, 200

# 時間足ごとのyfinance取得期間（RCI52期間に十分なデータを確保）
_INTERVAL_PERIODS = {
    "1h": "730d",
    "4h": "60d",
}

EXIT_SIGNAL_LABELS = {
    "DC":         "▼RCIエグジット（売り）",
    "STOP_LOSS":  "■損切り",
    "TAKE_PROFIT": "●利確",
}

EXIT_SIGNAL_LABELS_SHORT = {
    "DC":         "▲RCIエグジット（買い戻し）",
    "STOP_LOSS":  "■損切り",
    "TAKE_PROFIT": "●利確",
}

_REASON_LABELS = {
    "RCI_ENTRY":  "RCI反転シグナル（エントリー）",
    "RCI_EXIT":   "RCI反転シグナル（エグジット）",
    "STOP_LOSS":  "損切りライン到達",
    "TAKE_PROFIT": "利確ライン到達",
    "MANUAL":     "手動クローズ",
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


def append_trade_history(spreadsheet, history_row: list) -> None:
    """「FXトレード履歴」シートに1行追記する。書き込みエラーは警告のみで処理を止めない。"""
    try:
        hist_sheet = spreadsheet.worksheet("FXトレード履歴")
        hist_sheet.append_row(history_row, value_input_option="USER_ENTERED")
        print(f"[履歴] {history_row[3]} {history_row[1]} → Sheets記録完了")
    except Exception as e:
        print(f"[警告] 履歴書き込みエラー: {e}")


def send_trade_email(pair_name: str, action: str, direction: str, price: float, reason: str, pnl_pips=None) -> None:
    """エントリー/エグジット発生時にResendでメール通知する。"""
    api_key = os.environ.get("RESEND_API_KEY")
    notify_to = os.environ.get("NOTIFY_TO")
    if not api_key or not notify_to:
        print("[INFO] RESEND_API_KEY/NOTIFY_TO未設定のためメール通知をスキップします")
        return

    action_label = "エントリー" if action == "ENTRY" else "エグジット"
    reason_label = _REASON_LABELS.get(reason, reason)
    icon = "🟢" if action == "ENTRY" else "🔴"

    lines = [
        f"{pair_name} で {direction}{action_label} を記録しました。",
        "",
        f"アクション : {action_label}",
        f"理由       : {reason_label}",
        f"価格       : {price:,.4f}",
    ]
    if pnl_pips is not None:
        lines.append(f"損益       : {pnl_pips:+.1f} pips")

    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "from": "onboarding@resend.dev",
                "to": [notify_to],
                "subject": f"{icon} {pair_name} {direction}{action_label}",
                "text": "\n".join(lines),
            },
            timeout=10,
        )
        response.raise_for_status()
        print(f"[メール] {pair_name} {action_label} 通知送信")
    except Exception as e:
        print(f"[警告] メール送信エラー: {e}")


def compute_pair_update(ticker_code: str, row: dict, interval: str = "4h", rci_periods: dict | None = None) -> dict | None:
    """1通貨ペアの最新シグナル・ポジション更新内容を計算する（RCI戦略）。

    interval: "1h" or "4h"（シグナル検出用時間足）
    rci_periods: RCI期間設定（省略時はRCI_PERIODS=9/26/52を使用）
    """
    period = _INTERVAL_PERIODS.get(interval, "60d")
    rci_periods = rci_periods or RCI_PERIODS

    hist = yf.Ticker(ticker_code).history(interval=interval, period=period)
    if len(hist) < max(SLOW + 1, rci_periods["long"] + 1):
        return None

    df = attach_indicators(_to_ohlc_df(hist), fast=FAST, slow=SLOW, ma_type="ema")
    df = attach_rci(df, periods=rci_periods)

    curr = df.iloc[-1]

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

    direction = _resolve_direction(row)
    position = _build_position(row, direction)
    original_entry_price = position.entry_price  # EXIT時のpnl計算のために保存

    # RCIシグナルでエントリー/エグジット判定（EMAクロスではなく短期RCI反転を使用）
    rci_signals = detect_rci_signal_series(df, direction=direction)
    cross = rci_signals.iloc[-1]
    rci_short_val = round(curr["rci_short"], 1) if not pd.isna(curr["rci_short"]) else None

    stop_loss_pips = _to_pips(row.get("損切りpips"))
    take_profit_pips = _to_pips(row.get("利確pips"))
    new_position, event = step_position(
        position, cross, current_price, curr["time"],
        mode="pips", stop_loss_pips=stop_loss_pips, take_profit_pips=take_profit_pips,
        pip_multiplier_value=pip_multiplier(ticker_code), direction=direction,
    )

    # 履歴・メール用にDC理由をRCI_EXITに変換
    if event and event["reason"] == "DC":
        event = {**event, "reason": "RCI_EXIT"}

    if event and event["action"] == "ENTRY":
        signal = "★RCIエントリー（ショート）" if direction == "short" else "★RCIエントリー（買い）"
    elif event and event["action"] == "EXIT":
        labels = EXIT_SIGNAL_LABELS_SHORT if direction == "short" else EXIT_SIGNAL_LABELS
        signal = labels.get(event.get("reason", "DC"), "安定")
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
        "event": event,
        "rci_short_val": rci_short_val,
        "direction": direction,
        "original_entry_price": original_entry_price,
    }


def update_fx_watchlist_with_signals(sheet=None, spreadsheet=None, target_pairs=None, interval: str = "4h"):
    """FXウォッチリストの全銘柄（またはtarget_pairsで絞った銘柄）を更新する。

    interval: シグナル検出に使う時間足（"1h" or "4h"）
    target_pairs を指定すると、その通貨ペア名のみを更新する（API呼び出し削減用）。
    エントリー/エグジット発生時はSheetsの履歴シートへの記録とメール通知を行う。
    """
    print(f"\n--- 【FXウォッチリスト】のRCIシグナル更新を開始します（{interval}足）---")
    if sheet is None:
        spreadsheet = spreadsheet or _connect()
        try:
            sheet = spreadsheet.worksheet("FXウォッチリスト")
        except Exception as e:
            print(f"タブ【FXウォッチリスト】が見つかりません: {e}")
            return

    # 履歴書き込み用にSpreadsheetオブジェクトを確保
    spr = getattr(sheet, "spreadsheet", None) or spreadsheet or _connect()

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
            result = compute_pair_update(ticker_code, row, interval=interval)
            if result is None:
                print(f"[警告] {ticker_code} データ不足（SLOW={SLOW}本未満）")
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
                "event": result["event"],
                "pair_name": pair_name,
                "ticker_code": ticker_code,
                "direction": result["direction"],
                "original_entry_price": result["original_entry_price"],
                "rci_short_val": result["rci_short_val"],
                "interval": interval,
            })
            print(f"[取得] {pair_name} ({ticker_code}) 現在値:{result['current_price']}")
        except Exception as e:
            print(f"[エラー] {ticker_code}: {e}")

        time.sleep(1.2)

    print(f"\n--- フェーズ2: {len(all_updates)}銘柄を書き込み中 ---")
    for item in all_updates:
        row_idx = item["row"]
        vals = item["values"]
        sheet.batch_update([
            {"range": f"C{row_idx}:I{row_idx}", "values": [vals[:7]]},
            {"range": f"L{row_idx}:M{row_idx}", "values": [vals[7:]]},
        ])
        time.sleep(1.2)

        event = item["event"]
        if event:
            action = event["action"]
            reason = event["reason"]
            price = event["price"]
            direction_label = "ショート" if item["direction"] == "short" else "ロング"

            pnl_pips = None
            if action == "EXIT" and item["original_entry_price"]:
                pm_val = pip_multiplier(item["ticker_code"])
                if item["direction"] == "long":
                    pnl_pips = round((price - item["original_entry_price"]) * pm_val, 1)
                else:
                    pnl_pips = round((item["original_entry_price"] - price) * pm_val, 1)

            history_row = [
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                item["pair_name"],
                direction_label,
                action,
                price,
                reason,
                pnl_pips if pnl_pips is not None else "",
                item["interval"],
                item["rci_short_val"] if item["rci_short_val"] is not None else "",
            ]
            append_trade_history(spr, history_row)
            send_trade_email(item["pair_name"], action, direction_label, price, reason, pnl_pips)

        print(f"[書き込み完了] {item['label']}")


if __name__ == "__main__":
    update_fx_watchlist_with_signals()
    print("\nすべてのFXテクニカル指標の同期が完了しました！")
