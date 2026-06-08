import streamlit as st
import gspread
import pandas as pd
import yfinance as yf
import time
import json

# --- ページの設定（スマホ対応） ---
st.set_page_config(page_title="FX 投資ダッシュボード", layout="wide")

# --- パスワード保護 ---
def check_password():
    """Returns `True` if the user had the correct password."""
    # Secretsにパスワードが設定されていない場合は、保護なしで表示する
    if "app_password" not in st.secrets:
        return True

    def password_entered():
        if st.session_state["password"] == st.secrets["app_password"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # パスワードを保持しない
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.title("🔒 ログイン")
        st.text_input("パスワードを入力してください", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.title("🔒 ログイン")
        st.text_input("パスワードを入力してください", type="password", on_change=password_entered, key="password")
        st.error("😕 パスワードが間違っています")
        return False
    else:
        return True

if not check_password():
    st.stop()  # パスワードが正しくない場合はここで処理を停止し、以降のアプリ画面を描画しない

st.title("📊 FX ウォッチリスト Web App")
# --- Googleスプレッドシートへの接続設定 ---

@st.cache_resource
def init_connection():
    if "gcp_json" in st.secrets:
        creds_dict = json.loads(st.secrets["gcp_json"])
        from google.oauth2.service_account import Credentials
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        return gspread.authorize(creds)
    elif "gcp_service_account" in st.secrets:
        creds_dict = dict(st.secrets["gcp_service_account"])
        if "private_key" in creds_dict:
            creds_dict["private_key"] = creds_dict["private_key"].replace('\\n', '\n')
        from google.oauth2.service_account import Credentials
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        return gspread.authorize(creds)
    else:
        return gspread.service_account(filename="my-project-stock-498414-56d26f2c27b1.json")

def get_sheet(client):
    try:
        spreadsheet = client.open("kabu")
        return spreadsheet.worksheet("FXウォッチリスト")
    except Exception as e:
        st.error(f"スプレッドシートへの接続に失敗しました: {e}")
        return None

@st.cache_data(ttl=60)
def get_records(_sheet):
    if _sheet:
        return _sheet.get_all_records()
    return []

client = init_connection()
sheet = get_sheet(client)
records = get_records(sheet)

if records:
    # データを綺麗な表（DataFrame）に変換
    df = pd.DataFrame(records)
    
    # --- スマホ用：シグナルと通貨ペアでの絞り込み機能 ---
    st.subheader("🔍 通貨ペアスクリーニング")
    
    # 通貨ペアの選択ボックス（デフォルトを空にして、ユーザーが選ぶ仕様に。状態保持のためkeyを追加）
    all_pairs = df['通貨ペア名'].dropna().unique().tolist() if '通貨ペア名' in df.columns else []
    selected_pairs = st.multiselect("表示する通貨ペアを選択してください：", all_pairs, default=[], key="fx_selected_pairs")
    
    # シグナルの選択ボックス（初期状態でも選べるように固定シグナルを追加）
    fixed_signals = ["★ゴールデンクロス（買い）", "▼デッドクロス（売り）", "安定"]
    if 'シグナル' in df.columns:
        # スプレッドシート上の既存のシグナル（空文字以外）を取得
        existing_signals = [s for s in df['シグナル'].unique() if isinstance(s, str) and s.strip() != ""]
        # 重複を排除して結合
        all_signals = ["すべて"] + list(dict.fromkeys(fixed_signals + existing_signals))
    else:
        all_signals = ["すべて"] + fixed_signals
        
    selected_signal = st.selectbox("抽出したいシグナルを選択してください：", all_signals)
    
    # フィルター処理
    filtered_df = df.copy()
    if selected_pairs:
        filtered_df = filtered_df[filtered_df['通貨ペア名'].isin(selected_pairs)]
    else:
        filtered_df = pd.DataFrame(columns=df.columns) # 何も選択されていない場合は表示しない
        
    if selected_signal != "すべて":
        filtered_df = filtered_df[filtered_df['シグナル'] == selected_signal]
    
    # 件数の表示
    st.write(f"該当通貨ペア: **{len(filtered_df)}** 件")
    
    # パソコン画面にスクロールなしで収まるよう、列ごとの横幅を微調整
    st.data_editor(
        filtered_df, 
        use_container_width=True, 
        hide_index=True,
        column_config={
            "通貨ペア名": st.column_config.TextColumn("通貨ペア名", width="medium"),
            "Yahooティッカー": st.column_config.TextColumn("Yahooティッカー", width="small"),
            "現在値": st.column_config.NumberColumn("現在値", width="small"),
            "20EMA": st.column_config.NumberColumn("20EMA", width="small"),
            "200EMA": st.column_config.NumberColumn("200EMA", width="small"),
            "20EMA乖離率": st.column_config.TextColumn("20EMA乖離率", width="small"),
            "トレンド状態": st.column_config.TextColumn("トレンド状態", width="medium"),
            "シグナル": st.column_config.TextColumn("シグナル", width="medium"),
            "最終更新日時": st.column_config.TextColumn("最終更新日時", width="medium"),
        }
    )

    # --- スマホからPythonを遠隔起動するボタン ---
    st.markdown("---")
    st.subheader("⚙️ 遠隔コントロール")
    
    if st.button("🔄 表示中の通貨ペアのレートを最新に更新する", use_container_width=True):
        st.info("Yahoo Financeから最新データを収集中です... (画面を閉じずにしばらくお待ちください)")
        
        header = sheet.get_all_values()[0]
        updated_rows = []
        progress_bar = st.progress(0) # 画面に進捗バーを表示
        
        # 表示中の通貨ペアリストを取得
        active_pairs = filtered_df['通貨ペア名'].tolist() if not filtered_df.empty else []
        
        for idx, row in enumerate(records, start=2):
            ticker_code = str(row.get('Yahooティッカー', '')).strip()
            pair_name = row.get('通貨ペア名', '')
            
            # ティッカーが無い、または現在画面に表示されていない通貨ペアはスキップ（スプレッドシートの既存データを維持）
            if not ticker_code or ticker_code == 'nan' or pair_name not in active_pairs:
                updated_rows.append([row.get(h, '') for h in header])
                continue
                
            current_price = row.get('現在値', '')
            ema20_value = row.get('20EMA', '')
            ema200_value = row.get('200EMA', '')
            kairi_str = row.get('20EMA乖離率', '')
            trend = row.get('トレンド状態', 'レンジ')
            signal = row.get('シグナル', '安定')
            
            try:
                ticker = yf.Ticker(ticker_code)
                hist = ticker.history(interval='4h', period='60d') 
                if len(hist) >= 200:
                    hist['EMA20'] = hist['Close'].ewm(span=20, adjust=False).mean()
                    hist['EMA200'] = hist['Close'].ewm(span=200, adjust=False).mean()
                    
                    if not pd.isna(hist['EMA20'].iloc[-1]):
                        current_price = round(hist['Close'].iloc[-1], 3)
                        ema20_value = round(hist['EMA20'].iloc[-1], 3)
                        ema200_value = round(hist['EMA200'].iloc[-1], 3)
                        
                        kairi = round(((current_price - ema20_value) / ema20_value) * 100, 2)
                        kairi_str = f"{kairi}%"
                        
                        # パーフェクトオーダー判定
                        if current_price > ema20_value > ema200_value:
                            trend = "強い上昇"
                        elif current_price < ema20_value < ema200_value:
                            trend = "強い下降"
                        elif current_price > ema20_value:
                            trend = "やや上昇"
                        elif current_price < ema20_value:
                            trend = "やや下降"
                        
                        if len(hist) >= 2 and not pd.isna(hist['EMA20'].iloc[-2]) and not pd.isna(hist['EMA200'].iloc[-2]):
                            prev_ema20 = hist['EMA20'].iloc[-2]
                            prev_ema200 = hist['EMA200'].iloc[-2]
                            curr_ema20 = hist['EMA20'].iloc[-1]
                            curr_ema200 = hist['EMA200'].iloc[-1]
                            
                            if prev_ema20 <= prev_ema200 and curr_ema20 > curr_ema200:
                                signal = "★ゴールデンクロス（買い）"
                            elif prev_ema20 >= prev_ema200 and curr_ema20 < curr_ema200:
                                signal = "▼デッドクロス（売り）"
            except:
                pass
                
            time.sleep(0.1) # 高速化のため待機を0.1秒に縮小
            
            # 進捗バーの更新
            progress_bar.progress(idx / (len(records) + 1))
            
            # 更新データ辞書の作成
            updated_data = {
                '通貨ペア名': row.get('通貨ペア名', ''),
                'Yahooティッカー': ticker_code,
                '現在値': current_price,
                '20EMA': ema20_value,
                '200EMA': ema200_value,
                '20EMA乖離率': kairi_str,
                'トレンド状態': trend,
                'シグナル': signal,
            }
            
            # 処理対象だった場合は更新日時をセット
            if pair_name in active_pairs and ticker_code and ticker_code != 'nan':
                updated_data['最終更新日時'] = pd.Timestamp.now(tz='Asia/Tokyo').strftime('%Y-%m-%d %H:%M:%S')
            else:
                updated_data['最終更新日時'] = row.get('最終更新日時', '')

            # スプレッドシートの実際のヘッダー順に従ってリスト化（存在しない列があってもエラーにならない）
            new_row = [updated_data.get(h, row.get(h, '')) for h in header]
            updated_rows.append(new_row)
            
        # 一括書き込み
        cell_list = sheet.range(2, 1, len(updated_rows) + 1, len(header))
        flat_data = []
        for r in updated_rows:
            flat_data.extend(r)
        for i, cell in enumerate(cell_list):
            cell.value = flat_data[i]
        sheet.update_cells(cell_list)
        
        st.success("✨ データ取得と同期が完了しました！表示を更新します...")
        get_records.clear() # キャッシュを破棄して最新データを読み直す準備
        time.sleep(1.5) # メッセージを読ませるための待機
        st.rerun() # 自動でページを再読み込み（これにより選択状態が保持されたまま画面が更新されます）
