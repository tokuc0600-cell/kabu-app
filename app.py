import streamlit as st
import gspread
import pandas as pd
import yfinance as yf
import time

# --- ページの設定（スマホ対応） ---
st.set_page_config(page_title="マイ投資ダッシュボード", layout="wide")

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

st.title("📊 株価ウォッチリスト Web App")

# --- Googleスプレッドシートへの接続設定 ---
@st.cache_resource
def init_connection():
    # Streamlit CloudのSecretsを使う場合（推奨）
    if "gcp_service_account" in st.secrets:
        from google.oauth2.service_account import Credentials
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
        return gspread.authorize(creds)
    else:
        # ローカル用
        return gspread.service_account(filename="my-project-stock-498414-56d26f2c27b1.json")

@st.cache_data(ttl=60) # 1分間データをキャッシュして高速化
def load_data(_client):
    try:
        spreadsheet = _client.open("kabu")
        sheet = spreadsheet.worksheet("ウォッチリスト")
        return sheet.get_all_records()
    except Exception as e:
        st.error(f"データの読み込みに失敗しました: {e}")
        return []

try:
    client = init_connection()
    spreadsheet = client.open("kabu")
    sheet = spreadsheet.worksheet("ウォッチリスト")
    records = load_data(client)
except Exception as e:
    st.error(f"スプレッドシート接続エラー: {e}")
    sheet = None
    records = []

if records:
    # データを綺麗な表（DataFrame）に変換
    df = pd.DataFrame(records)
    
    # --- 📱 スマホ用：シグナルでの絞り込み機能 ---
    st.subheader("🔍 銘柄スクリーニング")
    
    # 選択ボックスの作成
    all_signals = ["すべて"] + list(df['シグナル'].unique()) if 'シグナル' in df.columns else ["すべて"]
    selected_signal = st.selectbox("抽出したいシグナルを選択してください：", all_signals)
    
    # フィルター処理
    filtered_df = df.copy()
    if selected_signal != "すべて":
        filtered_df = filtered_df[filtered_df['シグナル'] == selected_signal]
    
    # 件数の表示
    st.write(f"該当銘柄: **{len(filtered_df)}** 件")
    
   # 📊 パソコン画面にスクロールなしで収まるよう、列ごとの横幅を微調整
    st.data_editor(
        filtered_df, 
        use_container_width=True, 
        hide_index=True, # 左端の余計な行番号（0, 1, 2...）を非表示にしてスペースを節約
        column_config={
            "銘柄コード": st.column_config.TextColumn("銘柄コード", width="small"),
            "銘柄名": st.column_config.TextColumn("銘柄名", width="medium"),
            "業種": st.column_config.TextColumn("業種", width="medium"),
            "現在値": st.column_config.NumberColumn("現在値", width="small"),
            "25日移動平均": st.column_config.NumberColumn("25日移動平均", width="small"),
            "25日乖離率": st.column_config.TextColumn("25日乖離率", width="small"),
            "シグナル": st.column_config.TextColumn("シグナル", width="medium"),
        }
    )

    # --- 🔄 スマホからPythonを遠隔起動するボタン ---
    st.markdown("---")
    st.subheader("⚙️ 遠隔コントロール")
    
    if st.button("🔄 今すぐ全銘柄の株価を最新に更新する", use_container_width=True):
        st.info("東証から最新データを収集中です... (画面を閉じずにしばらくお待ちください)")
        
        # 以前作った一括高速更新ロジックをここに移植
        header = sheet.get_all_values()[0]
        updated_rows = []
        progress_bar = st.progress(0) # 画面に進捗バーを表示
        
        for idx, row in enumerate(records, start=2):
            code = str(row.get('銘柄コード', '')).strip()
            if not code or code == 'nan':
                updated_rows.append([row.get(h, '') for h in header])
                continue
                
            ticker_code = f"{code}.T"
            current_price = row.get('現在値', '')
            ma25_value = row.get('25日移動平均', '')
            kairi_str = row.get('25日乖離率', '')
            signal = row.get('シグナル', '安定')
            
            try:
                ticker = yf.Ticker(ticker_code)
                hist = ticker.history(period='1y') 
                if not hist.empty:
                    hist['MA25'] = hist['Close'].rolling(window=25).mean()
                    hist['MA5'] = hist['Close'].rolling(window=5).mean()
                    
                    if not pd.isna(hist['MA25'].iloc[-1]):
                        current_price = round(hist['Close'].iloc[-1], 2)
                        ma25_value = round(hist['MA25'].iloc[-1], 2)
                        kairi = round(((current_price - ma25_value) / ma25_value) * 100, 2)
                        kairi_str = f"{kairi}%"
                        
                        if len(hist) >= 2 and not pd.isna(hist['MA5'].iloc[-2]) and not pd.isna(hist['MA25'].iloc[-2]):
                            prev_ma5 = hist['MA5'].iloc[-2]
                            prev_ma25 = hist['MA25'].iloc[-2]
                            curr_ma5 = hist['MA5'].iloc[-1]
                            curr_ma25 = hist['MA25'].iloc[-1]
                            
                            if prev_ma5 <= prev_ma25 and curr_ma5 > curr_ma25:
                                signal = "★ゴールデンクロス"
                            elif prev_ma5 >= prev_ma25 and curr_ma5 < curr_ma25:
                                signal = "▼デッドクロス"
                            elif current_price > ma25_value:
                                signal = "上昇トレンド"
                            elif current_price < ma25_value:
                                signal = "下降トレンド"
            except:
                pass
                
            time.sleep(0.1) # 高速化のため待機を0.1秒に縮小
            
            # 進捗バーの更新
            progress_bar.progress(idx / (len(records) + 1))
            
            new_row = [row.get('銘柄コード',''), row.get('銘柄名',''), row.get('業種',''), current_price, ma25_value, kairi_str, signal]
            updated_rows.append(new_row)
            
        # 一括書き込み
        cell_list = sheet.range(2, 1, len(updated_rows) + 1, len(header))
        flat_data = []
        for r in updated_rows:
            flat_data.extend(r)
        for i, cell in enumerate(cell_list):
            cell.value = flat_data[i]
        sheet.update_cells(cell_list)
        
        st.success("✨ スプレッドシートの一括高速同期が完全完了しました！ ページを再読み込みしてください。")