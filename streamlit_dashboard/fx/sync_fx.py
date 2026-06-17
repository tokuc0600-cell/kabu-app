import gspread
import yfinance as yf
import time
import pandas as pd
import os
import json
from datetime import datetime

# 1. Google Sheets APIへの認証接続
# GitHub Actions: 環境変数 GCP_SERVICE_ACCOUNT_JSON からJSON文字列を読む
# ローカル: credentials/ フォルダのJSONファイルを使う
try:
    gcp_json = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")
    if gcp_json:
        client = gspread.service_account_from_dict(json.loads(gcp_json))
    else:
        client = gspread.service_account(filename="../../credentials/my-project-stock-498414-56d26f2c27b1.json")
    spreadsheet = client.open("kabu")
except Exception as e:
    print(f"スプレッドシートのオープンに失敗しました: {e}")
    exit()

def update_fx_watchlist_with_signals():
    print(f"\n--- 【FXウォッチリスト】のテクニカル分析＆自動更新を開始します ---")
    try:
        sheet = spreadsheet.worksheet("FXウォッチリスト")
    except Exception as e:
        print(f"タブ【FXウォッチリスト】が見つかりません: {e}")
        return

    records = sheet.get_all_records()
    all_updates = []

    # フェーズ1: 全銘柄のデータを取得（書き込みなし）
    print("--- フェーズ1: データ取得 ---")
    for idx, row in enumerate(records, start=2):
        ticker_code = str(row.get('Yahooティッカー', '')).strip()
        pair_name = str(row.get('通貨ペア名', '')).strip()

        if not ticker_code or ticker_code == 'nan':
            continue

        try:
            ticker = yf.Ticker(ticker_code)
            hist = ticker.history(interval='4h', period='60d')

            if len(hist) >= 200:
                hist['EMA20'] = hist['Close'].ewm(span=20, adjust=False).mean()
                hist['EMA200'] = hist['Close'].ewm(span=200, adjust=False).mean()

                current_price = round(hist['Close'].iloc[-1], 3)
                ema20_value = round(hist['EMA20'].iloc[-1], 3)
                ema200_value = round(hist['EMA200'].iloc[-1], 3)
                kairi = round(((current_price - ema20_value) / ema20_value) * 100, 2)

                trend = "レンジ"
                signal = "安定"

                if current_price > ema20_value > ema200_value:
                    trend = "強い上昇"
                elif current_price < ema20_value < ema200_value:
                    trend = "強い下降"
                elif current_price > ema20_value:
                    trend = "やや上昇"
                elif current_price < ema20_value:
                    trend = "やや下降"

                if len(hist) >= 2:
                    prev_ema20 = hist['EMA20'].iloc[-2]
                    prev_ema200 = hist['EMA200'].iloc[-2]
                    curr_ema20 = hist['EMA20'].iloc[-1]
                    curr_ema200 = hist['EMA200'].iloc[-1]

                    if prev_ema20 <= prev_ema200 and curr_ema20 > curr_ema200:
                        signal = "★ゴールデンクロス（買い）"
                    elif prev_ema20 >= prev_ema200 and curr_ema20 < curr_ema200:
                        signal = "▼デッドクロス（売り）"

                updated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                all_updates.append({
                    'row': idx,
                    'values': [current_price, ema20_value, ema200_value, f"{kairi}%", trend, signal, updated_at],
                    'label': f"{pair_name} ({ticker_code})"
                })
                print(f"[取得] {pair_name} ({ticker_code}) 現在値:{current_price}")
            else:
                print(f"[警告] {ticker_code} データ不足（200本未満）")

        except Exception as e:
            print(f"[エラー] {ticker_code}: {e}")

        time.sleep(1.2)

    # フェーズ2: セルごとに書き込み（1.2秒間隔でレート制限対応）
    print(f"\n--- フェーズ2: {len(all_updates)}銘柄を書き込み中 ---")
    for item in all_updates:
        row = item['row']
        vals = item['values']
        cols = [3, 4, 5, 6, 7, 8, 9]  # C, D, E, F, G, H, I
        for col, val in zip(cols, vals):
            sheet.update_cell(row, col, val)
            time.sleep(1.2)
        print(f"[書き込み完了] {item['label']}")

# 🚀 実行
if __name__ == "__main__":
    update_fx_watchlist_with_signals()
    print("\nすべてのFXテクニカル指標の同期が完了しました！")
