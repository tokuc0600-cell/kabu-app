import sys
from pathlib import Path

import streamlit as st
import gspread
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backtest.strategy import calc_rsi, calc_macd, calc_rci, RCI_PERIODS, rci_formula_text
from backtest.engine import build_trades, summarize, to_engine_df
from backtest.detail_view import build_trade_detail_figure
from sync_kabu import update_watchlist_with_signals


def trend_from_kairi(kairi_value, strong_threshold: float = 3.0) -> str:
    """25日乖離率からトレンドを4段階で表す（FXのトレンド状態と粒度を揃えるため）。

    Sheetsの「25日乖離率」は文字列（例: "1.23%"）で保存されているため、ここで数値化する。
    """
    try:
        kairi = float(str(kairi_value).rstrip("%"))
    except (TypeError, ValueError):
        return "—"
    if kairi >= strong_threshold:
        return "強い上昇"
    if kairi >= 0:
        return "やや上昇"
    if kairi > -strong_threshold:
        return "やや下降"
    return "強い下降"

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
    "5日": "5d",
    "1ヶ月": "1mo",
    "2ヶ月": "2mo",
    "3ヶ月": "3mo",
    "6ヶ月": "6mo",
    "1年": "1y",
    "2年": "2y",
    "3年": "3y",
    "5年": "5y",
    "最大（20年）": "max",
}

# yfinanceの制約（分足は直近60日、1時間足は直近730日まで）に合わせて
# 時間足ごとに選択可能な表示期間を絞る
INTERVAL_OPTIONS = {
    "日足":    {"interval": "1d",  "periods": ["3ヶ月", "6ヶ月", "1年", "3年", "5年", "最大（20年）"]},
    "週足":    {"interval": "1wk", "periods": ["1年", "3年", "5年", "最大（20年）"]},
    "1時間足":  {"interval": "1h",  "periods": ["5日", "1ヶ月", "3ヶ月", "6ヶ月", "1年", "2年"]},
    "15分足":   {"interval": "15m", "periods": ["5日", "1ヶ月", "2ヶ月"]},
}

@st.cache_data(ttl=3600)
def load_chart_data(ticker_code: str, period: str, interval: str = "1d") -> pd.DataFrame:
    df = yf.download(ticker_code, period=period, interval=interval,
                     auto_adjust=True, progress=False)
    if df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    # yfinanceは取引時間中・終値未確定の最新行をClose等NaNで返すことがあるため除外する
    df = df.dropna(subset=["Close"])
    df["MA5"]  = df["Close"].rolling(window=5).mean()
    df["MA25"] = df["Close"].rolling(window=25).mean()
    df.index = pd.to_datetime(df.index)
    return df

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

        # 一覧は「銘柄名・現在値・シグナル・トレンド」のみに絞り、横に切れないようにする。
        # 25日移動平均・乖離率などの指標値は、チャート分析・バックテストタブで確認する運用にする。
        filtered = filtered.copy()
        filtered["トレンド"] = filtered.get("25日乖離率", pd.Series(dtype=object)).map(trend_from_kairi)
        compact_cols = [c for c in ["銘柄名", "現在値", "シグナル", "トレンド"] if c in filtered.columns]
        filtered_display = filtered.reset_index(drop=True)
        st.caption("👆 詳細を見るには、行の左端のチェックボックスをクリックしてください（銘柄名や数値部分のクリックでは選択されません）")
        selection = st.dataframe(
            filtered_display[compact_cols],
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="t1_watchlist_table",
            column_config={
                "銘柄名":   st.column_config.TextColumn("銘柄名",   width="medium"),
                "現在値":   st.column_config.NumberColumn("現在値", width="small"),
                "シグナル": st.column_config.TextColumn("シグナル", width="medium"),
                "トレンド": st.column_config.TextColumn("トレンド", width="medium"),
            },
        )

        selected_rows = selection.selection.rows if selection and selection.selection else []
        if selected_rows:
            detail_row = filtered_display.iloc[selected_rows[0]]
            st.markdown("---")
            st.subheader(f"🔎 詳細: {detail_row.get('銘柄名', '')}（{detail_row.get('銘柄コード', '')}）")
            d1, d2, d3 = st.columns(3)
            d1.metric("業種", detail_row.get("業種", "—"))
            d2.metric("ポジション状態", detail_row.get("ポジション状態", "—"))
            d2.metric("建値", detail_row.get("建値", "—") or "—")
            d3.metric("最終更新日時", detail_row.get("最終更新日時", "—"))

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
    col_sel, col_int, col_per = st.columns([2, 1, 1])

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

    with col_int:
        interval_label = st.selectbox("時間足：", list(INTERVAL_OPTIONS.keys()), key="t2_interval")
        interval_value = INTERVAL_OPTIONS[interval_label]["interval"]
        available_periods = INTERVAL_OPTIONS[interval_label]["periods"]

    with col_per:
        default_idx   = available_periods.index("1年") if "1年" in available_periods else 0
        period_label  = st.selectbox("表示期間：", available_periods, index=default_idx, key="t2_period")
        period_value  = PERIOD_OPTIONS[period_label]

    col_ema1, col_ema2 = st.columns(2)
    with col_ema1:
        disp_ema_fast = st.number_input("表示用EMA（短期）", min_value=2, max_value=100, value=20, step=1, key="t2_ema_fast")
    with col_ema2:
        disp_ema_slow = st.number_input("表示用EMA（長期）", min_value=5, max_value=300, value=75, step=5, key="t2_ema_slow")

    if selected_code:
        ticker_code = f"{selected_code}.T" if not selected_code.endswith(".T") else selected_code
        with st.spinner(f"{selected_label} のデータを取得中..."):
            df_chart = load_chart_data(ticker_code, period_value, interval_value)

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

            fig = make_subplots(
                rows=3, cols=1, shared_xaxes=True, row_heights=[0.55, 0.2, 0.25], vertical_spacing=0.03,
            )

            fig.add_trace(go.Candlestick(
                x=df_chart.index, open=df_chart["Open"], high=df_chart["High"], low=df_chart["Low"], close=df_chart["Close"],
                name="株価", increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
            ), row=1, col=1)

            fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart["MA5"], name="MA5", line=dict(color="#ff9800", width=1.5)), row=1, col=1)
            fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart["MA25"], name="MA25", line=dict(color="#2196f3", width=1.5)), row=1, col=1)

            # 表示専用EMA（strategy.py・Sheets設定とは独立。チャート確認用の重ね描き）
            ema_fast_disp = df_chart["Close"].ewm(span=disp_ema_fast, adjust=False).mean()
            ema_slow_disp = df_chart["Close"].ewm(span=disp_ema_slow, adjust=False).mean()
            fig.add_trace(go.Scatter(x=df_chart.index, y=ema_fast_disp, name=f"EMA{disp_ema_fast}", line=dict(color="#4caf50", width=1.5, dash="dot")), row=1, col=1)
            fig.add_trace(go.Scatter(x=df_chart.index, y=ema_slow_disp, name=f"EMA{disp_ema_slow}", line=dict(color="#9c27b0", width=1.5, dash="dot")), row=1, col=1)

            colors = ["#26a69a" if float(df_chart["Close"].iloc[i]) >= float(df_chart["Open"].iloc[i]) else "#ef5350" for i in range(len(df_chart))]
            fig.add_trace(go.Bar(x=df_chart.index, y=df_chart["Volume"], name="出来高", marker_color=colors, showlegend=False), row=2, col=1)

            # RSI（参考表示のみ。エントリー/エグジット判定には使わない）
            rsi = calc_rsi(df_chart["Close"])
            fig.add_trace(go.Scatter(x=df_chart.index, y=rsi, name="RSI(14)", line=dict(color="#e91e63", width=1.5)), row=3, col=1)
            fig.add_hline(y=70, line=dict(color="#666666", width=1, dash="dot"), row=3, col=1)
            fig.add_hline(y=30, line=dict(color="#666666", width=1, dash="dot"), row=3, col=1)

            fig.update_layout(
                title=f"{selected_label} {interval_label}チャート（{period_label}）",
                xaxis_rangeslider_visible=False, height=750, paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
                font=dict(color="#fafafa"), legend=dict(orientation="h", y=1.02, x=0), margin=dict(l=10, r=10, t=60, b=10),
            )
            fig.update_xaxes(gridcolor="#2d2d2d", showgrid=True)
            fig.update_yaxes(gridcolor="#2d2d2d", showgrid=True)
            fig.update_yaxes(range=[0, 100], row=3, col=1)

            st.plotly_chart(fig, use_container_width=True)

            # MACD（参考表示のみ。エントリー/エグジット判定には使わない）
            macd_line, signal_line, histogram = calc_macd(df_chart["Close"])
            fig_macd = make_subplots(rows=1, cols=1)
            hist_colors = ["#26a69a" if v >= 0 else "#ef5350" for v in histogram]
            fig_macd.add_trace(go.Bar(x=df_chart.index, y=histogram, name="ヒストグラム", marker_color=hist_colors, showlegend=False))
            fig_macd.add_trace(go.Scatter(x=df_chart.index, y=macd_line, name="MACD", line=dict(color="#2196f3", width=1.5)))
            fig_macd.add_trace(go.Scatter(x=df_chart.index, y=signal_line, name="シグナル", line=dict(color="#ff9800", width=1.5)))
            fig_macd.update_layout(
                title="MACD", height=250, paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
                font=dict(color="#fafafa"), legend=dict(orientation="h", y=1.1, x=0), margin=dict(l=10, r=10, t=40, b=10),
            )
            fig_macd.update_xaxes(gridcolor="#2d2d2d", showgrid=True)
            fig_macd.update_yaxes(gridcolor="#2d2d2d", showgrid=True)
            st.plotly_chart(fig_macd, use_container_width=True)

            # ─── ポジション操作（手動エントリー） ───────────
            st.markdown("---")
            st.subheader("📥 ポジション操作")
            watch_row = None
            if not df_watch.empty and "銘柄コード" in df_watch.columns:
                matches = df_watch[df_watch["銘柄コード"].astype(str).str.strip() == selected_code]
                if not matches.empty:
                    watch_row = matches.iloc[0]

            if watch_row is None:
                st.info("ウォッチリストに無い銘柄（手動入力）はポジション操作の対象外です。")
            else:
                position_state = str(watch_row.get("ポジション状態", "")).strip()
                entry_price_now = watch_row.get("建値", "")
                if position_state == "ロング中":
                    st.write(f"現在のポジション：**ロング中**（建値: ¥{entry_price_now}）")
                else:
                    st.write("現在のポジション：**ノーポジ**")
                    if st.button("🟢 ここでエントリーを記録", key="t2_manual_entry"):
                        try:
                            entry_client = init_connection()
                            entry_sheet = entry_client.open("kabu").worksheet("ウォッチリスト")
                            entry_records = entry_sheet.get_all_records()
                            row_idx = None
                            for i, r in enumerate(entry_records, start=2):
                                if str(r.get("銘柄コード", "")).strip() == selected_code:
                                    row_idx = i
                                    break
                            if row_idx is None:
                                st.error("Sheets上に該当銘柄の行が見つかりませんでした。")
                            else:
                                entry_sheet.update(f"J{row_idx}:K{row_idx}", [[round(price_now, 2), "ロング中"]])
                                st.success(f"エントリーを記録しました（建値: ¥{price_now:,.2f}）。画面を更新します。")
                                st.rerun()
                        except Exception as e:
                            st.error(f"エントリー記録に失敗しました: {e}")
    else:
        st.info("👆 上の選択欄から銘柄を選ぶか、銘柄コードを直接入力してください。")

# ═══════════════════════════════════════════
# タブ3：バックテスト
# ═══════════════════════════════════════════
with tab3:
    st.subheader("🔬 バックテスト")
    strategy_choice = st.selectbox("戦略を選択：", ["EMAクロス", "RCI（3line）"], key="t3_strategy")

    rci_periods = RCI_PERIODS
    if strategy_choice == "RCI（3line）":
        with st.expander("📐 RCI（3line）の算出方法・判定ルール"):
            st.markdown(rci_formula_text(rci_periods))
        col_r1, col_r2, col_r3 = st.columns(3)
        with col_r1:
            rci_short = st.number_input("RCI短期", min_value=2, max_value=50, value=RCI_PERIODS["short"], step=1, key="t3_rci_short")
        with col_r2:
            rci_mid = st.number_input("RCI中期", min_value=5, max_value=100, value=RCI_PERIODS["mid"], step=1, key="t3_rci_mid")
        with col_r3:
            rci_long = st.number_input("RCI長期", min_value=10, max_value=200, value=RCI_PERIODS["long"], step=1, key="t3_rci_long")
        rci_periods = {"short": rci_short, "mid": rci_mid, "long": rci_long}

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
        bt_period = st.selectbox("検証期間：", list(PERIOD_OPTIONS.keys()), index=8, key="t3_period")

    with col_b3:
        ema_label_suffix = "（判定条件）" if strategy_choice == "EMAクロス" else "（乖離率の表示用）"
        fast_ema = st.number_input(f"短期EMA{ema_label_suffix}", min_value=2, max_value=50,  value=20, step=1)
        slow_ema = st.number_input(f"長期EMA{ema_label_suffix}", min_value=10, max_value=500, value=75, step=5)

    col_b4, col_b5 = st.columns(2)
    with col_b4:
        stop_loss_pct = st.number_input("損切りライン（%・任意、0=無効）", min_value=0.0, max_value=50.0, value=0.0, step=0.5, key="t3_sl")
    with col_b5:
        take_profit_pct = st.number_input("利確ライン（%・任意、0=無効）", min_value=0.0, max_value=100.0, value=0.0, step=0.5, key="t3_tp")

    run_btn = st.button("▶ バックテスト実行", use_container_width=True, type="primary")

    # st.button()はクリックした瞬間のスクリプト実行でのみTrueになるため、
    # トレード詳細のセレクトボックス操作で再実行された際にも結果を表示し続けられるよう
    # session_stateに結果を保持する（保持しないと再実行時に結果ごと消えてしまう）
    if run_btn and bt_code:
        bt_ticker = f"{bt_code}.T" if not bt_code.endswith(".T") else bt_code
        with st.spinner(f"{bt_label} のデータでバックテスト中..."):
            df_bt = load_chart_data(bt_ticker, PERIOD_OPTIONS[bt_period])

        if df_bt.empty:
            st.error("データを取得できませんでした。銘柄コードを確認してください。")
            st.session_state.pop("t3_bt_result", None)
        else:
            df_eng = to_engine_df(df_bt)
            indicator = "rci" if strategy_choice == "RCI（3line）" else "ema"
            trades_df = build_trades(
                df_eng, fast=fast_ema, slow=slow_ema,
                stop_loss_pct=stop_loss_pct, take_profit_pct=take_profit_pct,
                is_fx=False, ma_type="ema",
                indicator=indicator, rci_periods=rci_periods,
            )
            summary = summarize(trades_df)

            # チャート表示用に指標を付与（小文字OHLC + ma_fast/ma_slow、timeをindexに）
            data_bt = df_eng.copy()
            data_bt["ma_fast"] = data_bt["close"].ewm(span=fast_ema, adjust=False).mean()
            data_bt["ma_slow"] = data_bt["close"].ewm(span=slow_ema, adjust=False).mean()
            if indicator == "rci":
                data_bt["rci_short"] = calc_rci(data_bt["close"], rci_periods["short"])
            data_bt = data_bt.set_index("time")

            st.session_state["t3_bt_result"] = {
                "trades_df": trades_df, "summary": summary, "data_bt": data_bt,
                "bt_label": bt_label, "fast_ema": fast_ema, "slow_ema": slow_ema, "bt_period": bt_period,
                "strategy_choice": strategy_choice,
            }

    result = st.session_state.get("t3_bt_result")
    # デプロイで内部スキーマを変えても、古いセッションに残ったキャッシュをそのまま使ってしまわないように検証する
    if result and not {"open", "high", "low", "close"}.issubset(result["data_bt"].columns):
        st.session_state.pop("t3_bt_result", None)
        result = None
    if result:
        trades_df  = result["trades_df"]
        summary    = result["summary"]
        data_bt    = result["data_bt"]
        bt_label   = result["bt_label"]
        fast_ema   = result["fast_ema"]
        slow_ema   = result["slow_ema"]
        bt_period  = result["bt_period"]
        strategy_choice_result = result.get("strategy_choice", "EMAクロス")
        is_rci = strategy_choice_result == "RCI（3line）" and "rci_short" in data_bt.columns

        if summary["total_trades"] > 0:
            s1, s2, s3, s4 = st.columns(4)
            s1.metric("取引回数", f"{summary['total_trades']} 回")
            s2.metric("勝率", f"{summary['win_rate']} %")
            s3.metric("プロフィットファクター", f"{summary['profit_factor']}")
            s4.metric("最大ドローダウン", f"{summary['max_drawdown']} %")
        else:
            st.warning(f"この期間・{strategy_choice_result}設定ではトレードが発生しませんでした。")

        if is_rci:
            fig_bt = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.05)
            fig_bt.add_trace(go.Scatter(x=data_bt.index, y=data_bt["close"], name="終値", line=dict(color="#fafafa", width=1)), row=1, col=1)
            fig_bt.add_trace(go.Scatter(x=data_bt.index, y=data_bt["rci_short"], name="RCI短期", line=dict(color="#26a69a", width=1.5)), row=2, col=1)
            fig_bt.add_hline(y=80, line=dict(color="#ef5350", width=1, dash="dot"), row=2, col=1)
            fig_bt.add_hline(y=-80, line=dict(color="#26a69a", width=1, dash="dot"), row=2, col=1)
            title = f"{bt_label} RCI（3line）バックテスト（{bt_period}）"
        else:
            fig_bt = go.Figure()
            fig_bt.add_trace(go.Scatter(x=data_bt.index, y=data_bt["close"], name="終値", line=dict(color="#fafafa", width=1)))
            fig_bt.add_trace(go.Scatter(x=data_bt.index, y=data_bt["ma_fast"], name=f"EMA{fast_ema}（短期）", line=dict(color="#ff9800", width=1.5)))
            fig_bt.add_trace(go.Scatter(x=data_bt.index, y=data_bt["ma_slow"], name=f"EMA{slow_ema}（長期）", line=dict(color="#2196f3", width=1.5)))
            title = f"{bt_label} EMA{fast_ema}/EMA{slow_ema} バックテスト（{bt_period}）"

        if not trades_df.empty:
            entry_row = dict(row=1, col=1) if is_rci else {}
            fig_bt.add_trace(go.Scatter(x=trades_df["signal_date"], y=trades_df["entry_price"], mode="markers", name="エントリー（買い）", marker=dict(symbol="triangle-up", size=12, color="#26a69a")), **entry_row)
            fig_bt.add_trace(go.Scatter(x=trades_df["exit_date"], y=trades_df["exit_price"], mode="markers", name="イグジット（売り）", marker=dict(symbol="triangle-down", size=12, color="#ef5350")), **entry_row)

        fig_bt.update_layout(
            title=title,
            height=450, paper_bgcolor="#0e1117", plot_bgcolor="#0e1117", font=dict(color="#fafafa"),
            legend=dict(orientation="h", y=1.02, x=0), margin=dict(l=10, r=10, t=60, b=10),
            xaxis=dict(gridcolor="#2d2d2d"), yaxis=dict(gridcolor="#2d2d2d"),
        )
        st.plotly_chart(fig_bt, use_container_width=True)

        if not trades_df.empty:
            st.subheader("📄 トレード一覧")
            st.caption("entry/exit_ema_*_kairi_pct：エントリー/エグジット時点の価格がEMAから何%離れていたか（EMA上＝プラス、EMA下＝マイナス）")
            st.dataframe(
                trades_df.style.map(
                    lambda v: "color: #26a69a" if isinstance(v, float) and v > 0 else ("color: #ef5350" if isinstance(v, float) and v < 0 else ""),
                    subset=["profit_loss"]
                ),
                use_container_width=True, hide_index=True,
            )

            # ─── トレード詳細表示（エントリー～エグジット期間の拡大表示） ───
            with st.expander("🔍 トレード詳細を表示（エントリー～エグジット期間）"):
                trade_records = trades_df.reset_index(drop=True)
                trade_labels = [
                    f"#{i+1}: {row['signal_date']} → {row['exit_date']}"
                    for i, row in trade_records.iterrows()
                ]
                col_dsel, col_dbars = st.columns([3, 1])
                with col_dsel:
                    selected_trade_label = st.selectbox("対象トレードを選択：", trade_labels, key="t3_detail_trade")
                with col_dbars:
                    n_bars = st.number_input("前後の余白本数", min_value=1, max_value=50, value=5, step=1, key="t3_detail_nbars")

                selected_trade = trade_records.iloc[trade_labels.index(selected_trade_label)].to_dict()
                try:
                    fig_detail = build_trade_detail_figure(
                        data_bt, selected_trade,
                        fast_col="ma_fast", slow_col="ma_slow",
                        n_bars=n_bars,
                        rci_col="rci_short" if is_rci else None,
                    )
                    st.plotly_chart(fig_detail, use_container_width=True)
                except Exception as e:
                    st.warning("トレード詳細の表示に失敗しました（再度「▶ バックテスト実行」を押すと直る場合があります）")
                    st.caption(f"data_bt列: {list(data_bt.columns)}")
                    st.exception(e)
