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

def update_fx_watchlist_with_signals():
    print(f"\n--- 【FXウォッチリスト】のテクニカル分析＆自動更新を開始します ---")
    try:
        sheet = spreadsheet.worksheet("FXウォッチリスト")
    except Exception as e:
        print(f"タブ【FXウォッチリスト】が見つかりません。先にスプレッドシートに作成してください: {e}")
        return

    records = sheet.get_all_records()
    
    for idx, row in enumerate(records, start=2):
        ticker_code = str(row.get('Yahooティッカー', '')).strip()
        pair_name = str(row.get('通貨ペア名', '')).strip()
        
        if not ticker_code or ticker_code == 'nan':
            continue
            
        try:
            # yfinanceから、4時間足データを取得（200EMAを計算するため約60日分を取得）
            ticker = yf.Ticker(ticker_code)
            hist = ticker.history(interval='4h', period='60d') 
            
            if len(hist) >= 200:
                # 20EMAと200EMAを計算
                hist['EMA20'] = hist['Close'].ewm(span=20, adjust=False).mean()
                hist['EMA200'] = hist['Close'].ewm(span=200, adjust=False).mean()
                
                # 最新の現在値とEMAを取得
                current_price = round(hist['Close'].iloc[-1], 3)
                ema20_value = round(hist['EMA20'].iloc[-1], 3)
                ema200_value = round(hist['EMA200'].iloc[-1], 3)
                
                # 20EMAからの乖離率を計算（％表記）
                kairi = round(((current_price - ema20_value) / ema20_value) * 100, 2)
                
                # --- トレンド状態とシグナル判定 ---
                trend = "レンジ"
                signal = "安定"
                
                # パーフェクトオーダー判定
                if current_price > ema20_value > ema200_value:
                    trend = "強い上昇"
                elif current_price < ema20_value < ema200_value:
                    trend = "強い下降"
                elif current_price > ema20_value:
                    trend = "やや上昇"
                elif current_price < ema20_value:
                    trend = "やや下降"
                
                if len(hist) >= 2:
                    # 前日の値
                    prev_ema20 = hist['EMA20'].iloc[-2]
                    prev_ema200 = hist['EMA200'].iloc[-2]
                    # 当日の値
                    curr_ema20 = hist['EMA20'].iloc[-1]
                    curr_ema200 = hist['EMA200'].iloc[-1]
                    
                    # 20EMAが200EMAを下から上に突き抜けたらゴールデンクロス
                    if prev_ema20 <= prev_ema200 and curr_ema20 > curr_ema200:
                        signal = "★ゴールデンクロス（買い）"
                    # 20EMAが200EMAを上から下に突き抜けたらデッドクロス
                    elif prev_ema20 >= prev_ema200 and curr_ema20 < curr_ema200:
                        signal = "▼デッドクロス（売り）"

                # スプレッドシートへ一括書き込み（API呼び出しを6回→1回に削減）
                # C:現在値, D:20EMA, E:200EMA, F:20EMA乖離率, G:トレンド状態, H:シグナル
                sheet.update([[current_price, ema20_value, ema200_value, f"{kairi}%", trend, signal]], f'C{idx}:H{idx}')
                
                print(f"[成功] {pair_name} ({ticker_code}) -> 現在値:{current_price} | 20EMA:{ema20_value} | 200EMA:{ema200_value} | 乖離率:{kairi}% | トレンド:{trend} | シグナル:{signal}")
            else:
                print(f"[警告] {ticker_code} のデータ数が足りません（200本未満）。")
                
        except Exception as e:
            print(f"[エラー] {ticker_code} の解析中に問題発生: {e}")
        
        # 安全のために1.2秒待機
        time.sleep(1.2)

# 🚀 実行
if __name__ == "__main__":
    update_fx_watchlist_with_signals()
    print("\nすべてのFXテクニカル指標の同期が完了しました！")
