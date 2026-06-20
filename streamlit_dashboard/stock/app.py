import os
os.system("pip install plotly yfinance")


# （ここから下は元のコードのままで大丈夫です！）
import streamlit as st
import gspread
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import time

from sync_kabu import update_watchlist_with_signals

# ─────────────────────────────────────────
# ページ設定
# ─────────────────────────────────────────
st.set_page_config(
    page_title="マイ投資ダッシュボード",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ─────────────────────────────────────────
# パスワード保護
# ─────────────────────────────────────────
def check_password():
    """Returns `True` if the user had the correct password."""
    if "app_password" not in st.secrets:
        return True

    def password_entered():
        if st.session_state["password"] == st.secrets["app_password"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.title("🔒 ログイン")
        st.text_input("パスワードを入力してください", type="password",
                      on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.title("🔒 ログイン")
        st.text_input("パスワードを入力してください", type="password",
                      on_change=password_entered, key="password")
        st.error("😕 パスワードが間違っています")
        return False
    else:
        return True

if not check_password():
    st.stop()

# ─────────────────────────────────────────
# Google Sheets 接続
# ─────────────────────────────────────────
def init_connection():
    """毎回キャッシュを介さず、最新の認証オブジェクトを生成する安全な接続関数"""
    if "gcp_service_account" in st.secrets:
        creds_dict = dict(st.secrets["gcp_service_account"])
        if "private_key" in creds_dict:
            creds_dict["private_key"] = creds_dict["private_key"].replace('\\n', '\n')
            
        from google.oauth2.service_account import Credentials
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        return gspread.authorize(creds)
    else:
        st.error("GCPの認証情報がSecretsに見つかりません。")
        st.stop()

def load_data():
    try:
        client = init_connection()
        spreadsheet = client.open("kabu")
        sheet = spreadsheet.worksheet("ウォッチリスト")
        return sheet.get_all_records()
    except Exception as e:
        st.error(f"データの読み込みに失敗しました: {e}")
        return []

# ─────────────────────────────────────────
# チャートデータ取得（1時間キャッシュ）
# ─────────────────────────────────────────
PERIOD_OPTIONS = {
    "3ヶ月": "3mo",
    "6ヶ月": "6mo",
    "1年": "1y",
    "3年": "3y",
    "5年": "5y",
    "最大（20年）": "max",
}

@st.cache_data(ttl=3600)
def load_chart_data(ticker_code: str, period: str) -> pd.DataFrame:
    df = yf.download(ticker_code, period=period, interval="1d",
                     auto_adjust=True, progress=False)
    if df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df["MA5"]  = df["Close"].rolling(window=5).mean()
    df["MA25"] = df["Close"].rolling(window=25).mean()
    df.index = pd.to_datetime(df.index)
    return df

# ─────────────────────────────────────────
# バックテスト関数
# ─────────────────────────────────────────
def run_backtest(df: pd.DataFrame, fast: int = 20, slow: int = 200):
    data = df[["Close"]].copy()
    data["ema_fast"] = data["Close"].ewm(span=fast, adjust=False).mean()
    data["ema_slow"] = data["Close"].ewm(span=slow, adjust=False).mean()
    data["signal"] = 0
    data.loc[data["ema_fast"] > data["ema_slow"], "signal"] = 1
    data["entry"] = (data["signal"] == 1) & (data["signal"].shift(1).fillna(0) == 0)
    data["exit"]  = (data["signal"] == 0) & (data["signal"].shift(1).fillna(0) == 1)

    trades = []
    in_pos = False
    entry_price, entry_time = None, None

    for ts, row in data.iterrows():
        if not in_pos and row["entry"]:
            in_pos = True
            entry_price = float(row["Close"])
            entry_time  = ts
        elif in_pos and row["exit"]:
            exit_price = float(row["Close"])
            ret = (exit_price / entry_price - 1) * 100
            trades.append({
                "エントリー日": entry_time.strftime("%Y-%m-%d"),
                "イグジット日": ts.strftime("%Y-%m-%d"),
                "エントリー値": round(entry_price, 2),
                "イグジット値": round(exit_price, 2),
                "リターン(%)": round(ret, 2),
            })
            in_pos = False

    trades_df = pd.DataFrame(trades)
    summary = {}
    if len(trades_df):
        summary["取引回数"]       = len(trades_df)
        summary["勝率(%)"]        = round((trades_df["リターン(%)"] > 0).mean() * 100, 1)
        summary["平均リターン(%)"] = round(trades_df["リターン(%)"].mean(), 2)
        summary["合計リターン(%)"] = round(trades_df["リターン(%)"].sum(), 2)
    return trades_df, summary, data

# ─────────────────────────────────────────
# メイン UI
# ─────────────────────────────────────────
st.title("📊 株価ウォッチリスト ダッシュボード")

records = load_data()
df_watch = pd.DataFrame(records) if records else pd.DataFrame()

# ─── タブ ───────────────────────────────
tab1, tab2, tab3 = st.tabs(["📋 ウォッチリスト", "📈 チャート分析", "🔬 バックテスト"])

# ═══════════════════════════════════════════
# タブ1：ウォッチリスト
# ═══════════════════════════════════════════
with tab1:
    if not df_watch.empty:
        st.subheader("🔍 銘柄スクリーニング")
        all_signals = (["すべて"] + list(df_watch["シグナル"].unique())
                       if "シグナル" in df_watch.columns else ["すべて"])
        selected_signal = st.selectbox("シグナルで絞り込み：", all_signals, key="t1_signal")

        filtered = df_watch.copy()
        if selected_signal != "すべて":
            filtered = filtered[filtered["シグナル"] == selected_signal]

        st.write(f"該当銘柄: **{len(filtered)}** 件")
        st.data_editor(
            filtered,
            use_container_width=True,
            hide_index=True,
            column_config={
                "銘柄コード":   st.column_config.TextColumn("銘柄コード",   width="small"),
                "銘柄名":       st.column_config.TextColumn("銘柄名",       width="medium"),
                "業種":         st.column_config.TextColumn("業種",         width="medium"),
                "現在値":       st.column_config.NumberColumn("現在値",      width="small"),
                "25日移動平均": st.column_config.NumberColumn("25日移動平均",width="small"),
                "25日乖離率":   st.column_config.TextColumn("25日乖離率",   width="small"),
                "シグナル":     st.column_config.TextColumn("シグナル",     width="medium"),
            },
        )

        # 遠隔更新ボタン
        st.markdown("---")
        st.subheader("⚙️ 遠隔コントロール")
        if st.button("🔄 今すぐ全銘柄の株価を最新に更新する", use_container_width=True):
            st.info("東証から最新データを収集中です... (画面を閉じずにしばらくお待ちください)")

            # 🚨 ボタンが押された瞬間に、使い回しではなく「完全に新鮮な接続」をその場で作る
            btn_client = init_connection()
            btn_spreadsheet = btn_client.open("kabu")
            btn_sheet = btn_spreadsheet.worksheet("ウォッチリスト")

            # backtest/strategy.pyに一元化されたロジックをsync_kabu.py経由で呼び出す
            update_watchlist_with_signals(sheet=btn_sheet)
            st.success("✨ スプレッドシートの一括更新が完了しました！ブラウザをリフレッシュ（F5）して最新データを反映してください。")
    else:
        st.warning("スプレッドシートからデータを読み込めませんでした。接続設定を確認してください。")

# ═══════════════════════════════════════════
# タブ2：チャート分析
# ═══════════════════════════════════════════
with tab2:
    st.subheader("📈 チャート分析")
    col_sel, col_per = st.columns([2, 1])

    with col_sel:
        if not df_watch.empty and "銘柄コード" in df_watch.columns:
            stock_options = []
            for _, r in df_watch.iterrows():
                code = str(r.get("銘柄コード","")).strip()
                name = str(r.get("銘柄名","")).strip()
                if code and code != "nan":
                    stock_options.append(f"{code} {name}")
            manual_input = st.text_input(
                "銘柄コードを直接入力（例: 7203）",
                placeholder="ウォッチリスト以外の銘柄を調べる場合",
                key="t2_manual"
            )
            if manual_input.strip():
                selected_code = manual_input.strip().replace(".T", "")
                selected_label = f"{selected_code}（手動入力）"
            elif stock_options:
                chosen = st.selectbox("ウォッチリストから選択：", stock_options, key="t2_stock")
                selected_code  = chosen.split(" ")[0].strip()
                selected_label = chosen
            else:
                selected_code  = ""
                selected_label = ""
        else:
            selected_code = st.text_input("銘柄コードを入力（例: 7203）", key="t2_only_manual").strip()
            selected_label = selected_code

    with col_per:
        period_label  = st.selectbox("表示期間：", list(PERIOD_OPTIONS.keys()), index=2, key="t2_period")
        period_value  = PERIOD_OPTIONS[period_label]

    if selected_code:
        ticker_code = f"{selected_code}.T" if not selected_code.endswith(".T") else selected_code
        with st.spinner(f"{selected_label} のデータを取得中..."):
            df_chart = load_chart_data(ticker_code, period_value)

        if df_chart.empty:
            st.error(f"「{ticker_code}」のデータが取得できませんでした。銘柄コードを確認してください。")
        else:
            last       = df_chart.iloc[-1]
            prev       = df_chart.iloc[-2] if len(df_chart) >= 2 else last
            price_now  = float(last["Close"])
            price_prev = float(prev["Close"])
            ma25_now   = float(last["MA25"]) if not pd.isna(last["MA25"]) else None
            ma5_now    = float(last["MA5"])  if not pd.isna(last["MA5"])  else None
            delta_day  = price_now - price_prev
            delta_pct  = delta_day / price_prev * 100

            if ma25_now:
                kairi = (price_now - ma25_now) / ma25_now * 100
                if ma5_now and ma25_now:
                    if ma5_now > ma25_now:
                        signal_now = "上昇トレンド 📈"
                    else:
                        signal_now = "下降トレンド 📉"
                else:
                    signal_now = "---"
            else:
                kairi = None
                signal_now = "---"

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("現在値", f"¥{price_now:,.2f}", f"{delta_day:+.2f} ({delta_pct:+.2f}%)")
            m2.metric("MA5",  f"¥{ma5_now:,.2f}"  if ma5_now  else "---")
            m3.metric("MA25", f"¥{ma25_now:,.2f}" if ma25_now else "---", f"乖離率 {kairi:+.2f}%" if kairi is not None else None)
            m4.metric("トレンド", signal_now)

            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.03)

            fig.add_trace(go.Candlestick(
                x=df_chart.index, open=df_chart["Open"], high=df_chart["High"], low=df_chart["Low"], close=df_chart["Close"],
                name="株価", increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
            ), row=1, col=1)

            fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart["MA5"], name="MA5", line=dict(color="#ff9800", width=1.5)), row=1, col=1)
            fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart["MA25"], name="MA25", line=dict(color="#2196f3", width=1.5)), row=1, col=1)

            colors = ["#26a69a" if float(df_chart["Close"].iloc[i]) >= float(df_chart["Open"].iloc[i]) else "#ef5350" for i in range(len(df_chart))]
            fig.add_trace(go.Bar(x=df_chart.index, y=df_chart["Volume"], name="出来高", marker_color=colors, showlegend=False), row=2, col=1)

            fig.update_layout(
                title=f"{selected_label} 日足チャート（{period_label}）",
                xaxis_rangeslider_visible=False, height=600, paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
                font=dict(color="#fafafa"), legend=dict(orientation="h", y=1.02, x=0), margin=dict(l=10, r=10, t=60, b=10),
            )
            fig.update_xaxes(gridcolor="#2d2d2d", showgrid=True)
            fig.update_yaxes(gridcolor="#2d2d2d", showgrid=True)

            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("👆 上の選択欄から銘柄を選ぶか、銘柄コードを直接入力してください。")

# ═══════════════════════════════════════════
# タブ3：バックテスト
# ═══════════════════════════════════════════
with tab3:
    st.subheader("🔬 EMAクロス バックテスト")
    col_b1, col_b2, col_b3 = st.columns([2, 1, 1])

    with col_b1:
        if not df_watch.empty and "銘柄コード" in df_watch.columns:
            bt_options = []
            for _, r in df_watch.iterrows():
                code = str(r.get("銘柄コード","")).strip()
                name = str(r.get("銘柄名","")).strip()
                if code and code != "nan":
                    bt_options.append(f"{code} {name}")
            bt_manual = st.text_input("銘柄コードを直接入力", placeholder="例: 7203", key="t3_manual")
            if bt_manual.strip():
                bt_code  = bt_manual.strip().replace(".T","")
                bt_label = f"{bt_code}（手動入力）"
            elif bt_options:
                bt_chosen = st.selectbox("銘柄を選択：", bt_options, key="t3_stock")
                bt_code   = bt_chosen.split(" ")[0].strip()
                bt_label  = bt_chosen
            else:
                bt_code, bt_label = "", ""
        else:
            bt_code  = st.text_input("銘柄コードを入力", key="t3_only_manual").strip()
            bt_label = bt_code

    with col_b2:
        bt_period = st.selectbox("検証期間：", list(PERIOD_OPTIONS.keys()), index=4, key="t3_period")

    with col_b3:
        fast_ema = st.number_input("短期EMA", min_value=2, max_value=50,  value=20, step=1)
        slow_ema = st.number_input("長期EMA", min_value=10, max_value=500, value=75, step=5)

    run_btn = st.button("▶ バックテスト実行", use_container_width=True, type="primary")

    if run_btn and bt_code:
        bt_ticker = f"{bt_code}.T" if not bt_code.endswith(".T") else bt_code
        with st.spinner(f"{bt_label} のデータでバックテスト中..."):
            df_bt = load_chart_data(bt_ticker, PERIOD_OPTIONS[bt_period])

        if df_bt.empty:
            st.error("データを取得できませんでした。銘柄コードを確認してください。")
        else:
            trades_df, summary, data_bt = run_backtest(df_bt, fast=fast_ema, slow=slow_ema)

            if summary:
                s1, s2, s3, s4 = st.columns(4)
                s1.metric("取引回数",       f"{summary.get('取引回数', 0)} 回")
                s2.metric("勝率",           f"{summary.get('勝率(%)', 0)} %")
                s3.metric("平均リターン",   f"{summary.get('平均リターン(%)', 0):+.2f} %")
                s4.metric("合計リターン",   f"{summary.get('合計リターン(%)', 0):+.2f} %")
            else:
                st.warning("この期間・EMA設定ではトレードが発生しませんでした。")

            fig_bt = go.Figure()
            fig_bt.add_trace(go.Scatter(x=data_bt.index, y=data_bt["Close"], name="終値", line=dict(color="#fafafa", width=1)))
            fig_bt.add_trace(go.Scatter(x=data_bt.index, y=data_bt["ema_fast"], name=f"EMA{fast_ema}（短期）", line=dict(color="#ff9800", width=1.5)))
            fig_bt.add_trace(go.Scatter(x=data_bt.index, y=data_bt["ema_slow"], name=f"EMA{slow_ema}（長期）", line=dict(color="#2196f3", width=1.5)))

            entries = data_bt[data_bt["entry"]]
            exits   = data_bt[data_bt["exit"]]
            fig_bt.add_trace(go.Scatter(x=entries.index, y=entries["Close"], mode="markers", name="エントリー（買い）", marker=dict(symbol="triangle-up", size=12, color="#26a69a")))
            fig_bt.add_trace(go.Scatter(x=exits.index, y=exits["Close"], mode="markers", name="イグジット（売り）", marker=dict(symbol="triangle-down", size=12, color="#ef5350")))

            fig_bt.update_layout(
                title=f"{bt_label} EMA{fast_ema}/EMA{slow_ema} バックテスト（{bt_period}）",
                height=450, paper_bgcolor="#0e1117", plot_bgcolor="#0e1117", font=dict(color="#fafafa"),
                legend=dict(orientation="h", y=1.02, x=0), margin=dict(l=10, r=10, t=60, b=10),
                xaxis=dict(gridcolor="#2d2d2d"), yaxis=dict(gridcolor="#2d2d2d"),
            )
            st.plotly_chart(fig_bt, use_container_width=True)

            if not trades_df.empty:
                st.subheader("📄 トレード一覧")
                st.dataframe(
                    trades_df.style.map(
                        lambda v: "color: #26a69a" if isinstance(v, float) and v > 0 else ("color: #ef5350" if isinstance(v, float) and v < 0 else ""),
                        subset=["リターン(%)"]
                    ),
                    use_container_width=True, hide_index=True,
                )