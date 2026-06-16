import gspread
import yfinance as yf
import time
import pandas as pd
import os
import json

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

def update_watchlist_with_signals():
    print(f"\n--- 【ウォッチリスト】のテクニカル分析＆自動更新を開始します ---")
    try:
        sheet = spreadsheet.worksheet("ウォッチリスト")
    except Exception as e:
        print(f"タブ【ウォッチリスト】が見つかりません: {e}")
        return

    records = sheet.get_all_records()
    
    for idx, row in enumerate(records, start=2):
        code = str(row.get('銘柄コード', '')).strip()
        if not code or code == 'nan':
            continue
            
        ticker_code = f"{code}.T"
        try:
            # yfinanceから、移動平均線の計算に必要な「過去6ヶ月分（90日強）」の日足データを一括取得
            ticker = yf.Ticker(ticker_code)
            hist = ticker.history(period='6m') # 6ヶ月分
            
            if len(hist) >= 25:
                # 25日移動平均線（MA25）を計算
                hist['MA25'] = hist['Close'].rolling(window=25).mean()
                # 5日移動平均線（MA5：クロス判定用）を計算
                hist['MA5'] = hist['Close'].rolling(window=5).mean()
                
                # 最新の現在値と25日移動平均値を取得
                current_price = round(hist['Close'].iloc[-1], 2)
                ma25_value = round(hist['MA25'].iloc[-1], 2)
                
                # 25日線からの乖離率を計算（％表記）
                kairi = round(((current_price - ma25_value) / ma25_value) * 100, 2)
                
                # --- 🤖 ゴールデンクロス/デッドクロスの自動判定ロジック ---
                signal = "安定"
                if len(hist) >= 2:
                    # 前日の値
                    prev_ma5 = hist['MA5'].iloc[-2]
                    prev_ma25 = hist['MA25'].iloc[-2]
                    # 当日の値
                    curr_ma5 = hist['MA5'].iloc[-1]
                    curr_ma25 = hist['MA25'].iloc[-1]
                    
                    # 5日線が25日線を下から上に突き抜けたらゴールデンクロス
                    if prev_ma5 <= prev_ma25 and curr_ma5 > curr_ma25:
                        signal = "★ゴールデンクロス（買いサイン）"
                    # 5日線が25日線を上から下に突き抜けたらデッドクロス
                    elif prev_ma5 >= prev_ma25 and curr_ma5 < curr_ma25:
                        signal = "▼デッドクロス（売り注意）"
                    # クロスはしていないが、25日線より上で強い状態
                    elif current_price > ma25_value:
                        signal = "上昇トレンド"
                    # 25日線より下で弱い状態
                    elif current_price < ma25_value:
                        signal = "下降トレンド"

                # スプレッドシートの指定した列（D, E, F, G）へ一気に書き込み
                sheet.update_cell(idx, 4, current_price) # D列: 現在値
                sheet.update_cell(idx, 5, ma25_value)    # E列: 25日移動平均
                sheet.update_cell(idx, 6, f"{kairi}%")   # F列: 25日乖離率
                sheet.update_cell(idx, 7, signal)        # G列: シグナル
                
                print(f"[成功] {row.get('銘柄名', code)} ({code}) -> 現在値:{current_price}円 | 25日線:{ma25_value}円 | 乖離率:{kairi}% | 状態:{signal}")
            else:
                print(f"[警告] {code} のデータ数が足りません（25日未満）。")
                
        except Exception as e:
            print(f"[エラー] {code} の解析中に問題発生: {e}")
        
        # 安全のために1.2秒待機
        time.sleep(1.2)

# 🚀 実行
update_watchlist_with_signals()
print("\nすべてのテクニカル指標の同期が完了しました！")