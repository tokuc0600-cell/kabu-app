"""保有中の株式銘柄がエグジット閾値（損切/利確）に到達したらメール通知する。

Sheetsの銘柄ごとの損切%・利確%は読まず、backtest/strategy.pyの
check_exit_by_pct（全銘柄一律の固定%）で判定する。対象は株のみ（FXは対象外）。
Sheetsへの書き込み・重複通知防止は行わない。
"""

import argparse
import json
import os
import smtplib
import sys
from email.mime.text import MIMEText
from pathlib import Path

import gspread
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest.strategy import STOP_LOSS_PCT, TAKE_PROFIT_PCT, check_exit_by_pct

REASON_LABELS = {
    "STOP_LOSS": "損切り",
    "TAKE_PROFIT": "利確",
}

MODE_MESSAGES = {
    "intraday": "本日中に決済可能です。",
    "close": "翌営業日の寄り付きで決済してください。",
}


def _connect():
    gcp_json = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")
    if gcp_json:
        client = gspread.service_account_from_dict(json.loads(gcp_json))
    else:
        creds_path = Path(__file__).resolve().parents[1] / "credentials" / "my-project-stock-498414-56d26f2c27b1.json"
        client = gspread.service_account(filename=str(creds_path))
    return client.open("kabu")


def _to_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_open_positions() -> list[dict]:
    """「ウォッチリスト」シートからロング中の銘柄（銘柄コード・銘柄名・建値）を抽出する。"""
    spreadsheet = _connect()
    sheet = spreadsheet.worksheet("ウォッチリスト")
    records = sheet.get_all_records()

    positions = []
    for row in records:
        if str(row.get("ポジション状態", "")).strip() != "ロング中":
            continue
        code = str(row.get("銘柄コード", "")).strip()
        entry_price = _to_float(row.get("建値"))
        if not code or entry_price is None:
            continue
        positions.append({
            "code": code,
            "name": str(row.get("銘柄名", code)).strip(),
            "entry_price": entry_price,
        })
    return positions


def fetch_current_price(code: str) -> float | None:
    ticker_code = f"{code}.T"
    hist = yf.Ticker(ticker_code).history(period="5d")
    if hist.empty:
        return None
    return float(hist["Close"].iloc[-1])


def build_email(position: dict, current_price: float, reason: str, mode: str) -> MIMEText:
    pnl_pct = (current_price - position["entry_price"]) / position["entry_price"] * 100
    reason_label = REASON_LABELS.get(reason, reason)
    subject = f"⚠️ {position['name']}（{position['code']}）が{reason_label}ラインに到達"
    body = (
        f"{position['name']}（{position['code']}）がエグジット条件に到達しました。\n\n"
        f"判定: {reason_label}\n"
        f"建値: {position['entry_price']:,.2f}円\n"
        f"現在値: {current_price:,.2f}円\n"
        f"損益: {pnl_pct:+.2f}%\n"
        f"閾値: 損切{STOP_LOSS_PCT}% / 利確{TAKE_PROFIT_PCT}%\n\n"
        f"{MODE_MESSAGES[mode]}"
    )
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = os.environ["GMAIL_ADDRESS"]
    msg["To"] = os.environ["NOTIFY_TO"]
    return msg


def send_email(msg: MIMEText) -> None:
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"])
        server.send_message(msg)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["intraday", "close"], required=True)
    args = parser.parse_args()

    positions = fetch_open_positions()
    if not positions:
        print("ロング中の銘柄はありません。対象なし。")
        return

    notified = 0
    for position in positions:
        current_price = fetch_current_price(position["code"])
        if current_price is None:
            print(f"[警告] {position['code']} の現在値が取得できませんでした。")
            continue

        reason = check_exit_by_pct(position["entry_price"], current_price)
        if reason is None:
            print(f"[対象外] {position['name']}（{position['code']}）建値:{position['entry_price']} 現在値:{current_price}")
            continue

        msg = build_email(position, current_price, reason, args.mode)
        send_email(msg)
        notified += 1
        print(f"[通知] {position['name']}（{position['code']}）-> {reason}")

    print(f"完了。{notified}件通知しました。")


if __name__ == "__main__":
    main()
