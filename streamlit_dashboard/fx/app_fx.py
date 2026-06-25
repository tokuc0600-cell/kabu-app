import sys
from pathlib import Path

import streamlit as st
import gspread
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import time
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backtest.strategy import (
    calc_rsi, calc_macd, calc_rci, pip_multiplier, RCI_PERIODS, rci_formula_text,
    calc_stochastic, calc_atr, calc_adx, calc_cci, calc_williams_r, judge_indicator_signal,
)
from backtest.engine import build_trades, summarize, to_engine_df
from backtest.detail_view import build_trade_detail_figure
from sync_fx import update_fx_watchlist_with_signals

# --- ページの設定（スマホ対応） ---
st.set_page_config(page_title="FX 投資ダッシュボード", layout="wide")

# --- パスワード保護 ---
def check_password():
    """Returns `True` if the user had the correct password."""
    # Secretsにパスワードが設定されていない場合は、保護なしで表示する
    if "app_password" not in st.secrets:
        st.warning("⚠️ デバッグ情報: Secretsに `app_password` が見つかりません。パスワード保護をスキップします。")
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
        return gspread.service_account(filename="../../credentials/my-project-stock-498414-56d26f2c27b1.json")

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

# ─────────────────────────────────────────
# チャート分析・バックテスト用の時間足・期間オプション
# ─────────────────────────────────────────
PERIOD_OPTIONS = {
    "1日": "1d",
    "5日": "5d",
    "1ヶ月": "1mo",
    "2ヶ月": "2mo",
    "3ヶ月": "3mo",
    "6ヶ月": "6mo",
    "1年": "1y",
    "2年": "2y",
    "3年": "3y",
    "5年": "5y",
    "最大": "max",
}

# yfinanceの制約（1分足は直近7日、5分・15分足は直近60日、1時間足は直近730日まで）に合わせて
# 時間足ごとに選択可能な表示期間を絞る
FX_INTERVAL_OPTIONS = {
    "1分足":   {"interval": "1m",  "periods": ["1日", "5日"]},
    "5分足":   {"interval": "5m",  "periods": ["5日", "1ヶ月", "2ヶ月"]},
    "15分足":  {"interval": "15m", "periods": ["5日", "1ヶ月", "2ヶ月"]},
    "1時間足": {"interval": "1h",  "periods": ["1ヶ月", "3ヶ月", "6ヶ月", "1年", "2年"]},
    "4時間足": {"interval": "4h",  "periods": ["1ヶ月", "3ヶ月", "6ヶ月", "1年", "2年"]},
    "日足":    {"interval": "1d",  "periods": ["3ヶ月", "6ヶ月", "1年", "3年", "5年", "最大"]},
    "週足":    {"interval": "1wk", "periods": ["1年", "3年", "5年", "最大"]},
}


@st.cache_data(ttl=3600)
def load_fx_chart_data(ticker_code: str, period: str, interval: str = "1d") -> pd.DataFrame:
    # 取得失敗時はst.cache_dataにキャッシュさせないよう例外を投げる
    # （空のDataFrameを返すと、Yahoo側の一時的な失敗が1時間キャッシュされ続けてしまう）
    df = yf.download(ticker_code, period=period, interval=interval, auto_adjust=True, progress=False)
    if df.empty:
        raise ValueError(f"データを取得できませんでした: {ticker_code} ({interval}, {period})")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    # yfinanceは取引時間中・終値未確定の最新行をClose等NaNで返すことがあるため除外する
    df = df.dropna(subset=["Close"])
    df.index = pd.to_datetime(df.index)
    return df


def build_technical_summary(df_chart: pd.DataFrame) -> pd.DataFrame:
    """investing.com風のテクニカル指標サマリー（指標名・現在値・判定）を返す。表示専用、判定には使わない。"""
    high, low, close = df_chart["High"], df_chart["Low"], df_chart["Close"]

    rsi_now = calc_rsi(close).iloc[-1]
    _, _, macd_hist = calc_macd(close)
    macd_now = macd_hist.iloc[-1]
    stoch_k, _ = calc_stochastic(high, low, close)
    stoch_now = stoch_k.iloc[-1]
    atr_now = calc_atr(high, low, close).iloc[-1]
    plus_di, minus_di, adx = calc_adx(high, low, close)
    adx_now = (plus_di.iloc[-1], minus_di.iloc[-1], adx.iloc[-1])
    cci_now = calc_cci(high, low, close).iloc[-1]
    willr_now = calc_williams_r(high, low, close).iloc[-1]
    rci_now = calc_rci(close, RCI_PERIODS["short"]).iloc[-1]

    rows = [
        ("RSI(14)", f"{rsi_now:.1f}" if pd.notna(rsi_now) else "—", judge_indicator_signal("RSI", rsi_now)),
        ("MACDヒストグラム", f"{macd_now:.5f}" if pd.notna(macd_now) else "—", judge_indicator_signal("MACD", macd_now)),
        ("ストキャスティクス%K", f"{stoch_now:.1f}" if pd.notna(stoch_now) else "—", judge_indicator_signal("Stochastic", stoch_now)),
        ("ADX", f"{adx_now[2]:.1f}" if pd.notna(adx_now[2]) else "—", judge_indicator_signal("ADX", adx_now)),
        ("CCI(20)", f"{cci_now:.1f}" if pd.notna(cci_now) else "—", judge_indicator_signal("CCI", cci_now)),
        ("Williams %R", f"{willr_now:.1f}" if pd.notna(willr_now) else "—", judge_indicator_signal("WilliamsR", willr_now)),
        ("RCI短期", f"{rci_now:.1f}" if pd.notna(rci_now) else "—", judge_indicator_signal("RCI", rci_now)),
        ("ATR(14)", f"{atr_now:.5f}" if pd.notna(atr_now) else "—", "—"),
    ]
    return pd.DataFrame(rows, columns=["指標", "現在値", "判定"])


# ─── タブ ───────────────────────────────
tab1, tab2, tab3 = st.tabs(["📋 ウォッチリスト", "📈 チャート分析", "🔬 バックテスト"])

# ═══════════════════════════════════════════
# タブ1：ウォッチリスト（既存機能、変更なし）
# ═══════════════════════════════════════════
with tab1:
    if records:
        # データを綺麗な表（DataFrame）に変換
        df = pd.DataFrame(records)

        # --- スマホ用：シグナルと通貨ペアでの絞り込み機能 ---
        st.subheader("🔍 通貨ペアスクリーニング")

        # 通貨ペアの選択ボックス（株のウォッチリストと同様、未選択時は全件表示。絞り込みたい場合のみ選択）
        all_pairs = df['通貨ペア名'].dropna().unique().tolist() if '通貨ペア名' in df.columns else []
        selected_pairs = st.multiselect("通貨ペアで絞り込む（任意・未選択なら全件表示）：", all_pairs, default=[], key="fx_selected_pairs")

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

        # フィルター処理（未選択時は全件、選択時はその通貨ペアのみに絞る）
        filtered_df = df.copy()
        if selected_pairs:
            filtered_df = filtered_df[filtered_df['通貨ペア名'].isin(selected_pairs)]

        if selected_signal != "すべて":
            filtered_df = filtered_df[filtered_df['シグナル'] == selected_signal]

        # 件数の表示
        st.write(f"該当通貨ペア: **{len(filtered_df)}** 件")

        # 一覧は「通貨ペア名・現在値・シグナル・トレンド状態」のみに絞り、横に切れないようにする。
        # EMA数値・乖離率などの指標値は、チャート分析・バックテストタブで確認する運用にする。
        compact_cols = [c for c in ["通貨ペア名", "現在値", "シグナル", "トレンド状態"] if c in filtered_df.columns]
        filtered_display = filtered_df.reset_index(drop=True)
        st.caption("👆 詳細を見るには、行の左端のチェックボックスをクリックしてください（通貨ペア名や数値部分のクリックでは選択されません）")
        fx_selection = st.dataframe(
            filtered_display[compact_cols],
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="t1_fx_table",
            column_config={
                "通貨ペア名":   st.column_config.TextColumn("通貨ペア名", width="medium"),
                "現在値":       st.column_config.NumberColumn("現在値",   width="small"),
                "シグナル":     st.column_config.TextColumn("シグナル",   width="medium"),
                "トレンド状態": st.column_config.TextColumn("トレンド状態", width="medium"),
            }
        )

        fx_selected_rows = fx_selection.selection.rows if fx_selection and fx_selection.selection else []
        if fx_selected_rows:
            fx_detail = filtered_display.iloc[fx_selected_rows[0]]
            st.markdown("---")
            st.subheader(f"🔎 詳細: {fx_detail.get('通貨ペア名', '')}（{fx_detail.get('Yahooティッカー', '')}）")
            f1, f2 = st.columns(2)
            f1.metric("ポジション状態", fx_detail.get("ポジション状態", "—"))
            f1.metric("建値", fx_detail.get("建値", "—"))
            f1.metric("売買方向", fx_detail.get("売買方向", "ロング") or "ロング")
            f2.metric("最終更新日時", fx_detail.get("最終更新日時", "—"))

            detail_ticker = str(fx_detail.get("Yahooティッカー", "")).strip()
            if detail_ticker:
                try:
                    detail_chart = load_fx_chart_data(detail_ticker, "6mo", "1d")
                except ValueError:
                    detail_chart = pd.DataFrame()
                if not detail_chart.empty and len(detail_chart) >= 25:
                    st.markdown("##### 📊 テクニカルサマリー（参考表示・判定には使用しません）")
                    summary_df = build_technical_summary(detail_chart)
                    buy_count = (summary_df["判定"] == "買い").sum()
                    sell_count = (summary_df["判定"] == "売り").sum()
                    st.caption(f"買い: {buy_count}件 / 中立: {(summary_df['判定'] == '中立').sum()}件 / 売り: {sell_count}件")
                    st.dataframe(summary_df, use_container_width=True, hide_index=True)

        # --- スマホからPythonを遠隔起動するボタン ---
        st.markdown("---")
        st.subheader("⚙️ 遠隔コントロール")

        if st.button("🔄 表示中の通貨ペアのレートを最新に更新する", use_container_width=True):
            # 表示中の通貨ペアのみ更新（backtest/strategy.pyに一元化されたロジックをsync_fx.py経由で呼び出す）
            active_pairs = filtered_df['通貨ペア名'].tolist() if not filtered_df.empty else []
            # yfinance取得+Sheets書き込みでペアごとに約2.4秒かかる想定（sync_fx.py内のレート制限スリープ込み）
            est_sec = len(active_pairs) * 2.4
            st.info(
                f"Yahoo Financeから最新データを収集中です（対象 {len(active_pairs)} 件・推定 {est_sec:.0f} 秒）... "
                "(画面を閉じずにしばらくお待ちください)"
            )

            try:
                update_fx_watchlist_with_signals(sheet=sheet, target_pairs=active_pairs)
                st.success("✨ データ取得と同期が完了しました！表示を更新します...")
                get_records.clear() # キャッシュを破棄して最新データを読み直す準備
                time.sleep(1.5) # メッセージを読ませるための待機
                st.rerun() # 自動でページを再読み込み（これにより選択状態が保持されたまま画面が更新されます）
            except Exception as e:
                st.error(f"レート更新中にエラーが発生しました。時間を置いて再度お試しください: {e}")
    else:
        st.warning("スプレッドシートからデータを読み込めませんでした。接続設定を確認してください。")

# ═══════════════════════════════════════════
# タブ2：チャート分析
# ═══════════════════════════════════════════
with tab2:
    st.subheader("📈 チャート分析")
    df_watch = pd.DataFrame(records) if records else pd.DataFrame()
    col_sel, col_int, col_per = st.columns([2, 1, 1])

    with col_sel:
        if not df_watch.empty and "Yahooティッカー" in df_watch.columns:
            pair_options = []
            for _, r in df_watch.iterrows():
                ticker = str(r.get("Yahooティッカー", "")).strip()
                name = str(r.get("通貨ペア名", "")).strip()
                if ticker and ticker != "nan":
                    pair_options.append(f"{ticker} {name}")
            manual_input = st.text_input(
                "Yahooティッカーを直接入力（例: USDJPY=X）",
                placeholder="ウォッチリスト以外の通貨ペアを調べる場合",
                key="t2_manual"
            )
            if manual_input.strip():
                selected_ticker = manual_input.strip()
                selected_label = f"{selected_ticker}（手動入力）"
            elif pair_options:
                chosen = st.selectbox("ウォッチリストから選択：", pair_options, key="t2_pair")
                selected_ticker = chosen.split(" ")[0].strip()
                selected_label = chosen
            else:
                selected_ticker = ""
                selected_label = ""
        else:
            selected_ticker = st.text_input("Yahooティッカーを入力（例: USDJPY=X）", key="t2_only_manual").strip()
            selected_label = selected_ticker

    with col_int:
        interval_label = st.selectbox("時間足：", list(FX_INTERVAL_OPTIONS.keys()), index=5, key="t2_interval")
        interval_value = FX_INTERVAL_OPTIONS[interval_label]["interval"]
        available_periods = FX_INTERVAL_OPTIONS[interval_label]["periods"]

    with col_per:
        default_idx = available_periods.index("1年") if "1年" in available_periods else 0
        period_label = st.selectbox("表示期間：", available_periods, index=default_idx, key="t2_period")
        period_value = PERIOD_OPTIONS[period_label]

    col_ema1, col_ema2 = st.columns(2)
    with col_ema1:
        disp_ema_fast = st.number_input("表示用EMA（短期）", min_value=2, max_value=100, value=20, step=1, key="t2_ema_fast")
    with col_ema2:
        disp_ema_slow = st.number_input("表示用EMA（長期）", min_value=5, max_value=300, value=200, step=5, key="t2_ema_slow")

    if selected_ticker:
        with st.spinner(f"{selected_label} のデータを取得中..."):
            try:
                df_chart = load_fx_chart_data(selected_ticker, period_value, interval_value)
            except ValueError:
                df_chart = pd.DataFrame()

        if df_chart.empty:
            st.error(f"「{selected_ticker}」のデータが取得できませんでした。ティッカーを確認してください。")
        else:
            last = df_chart.iloc[-1]
            prev = df_chart.iloc[-2] if len(df_chart) >= 2 else last
            price_now = float(last["Close"])
            price_prev = float(prev["Close"])
            delta_day = price_now - price_prev
            delta_pct = delta_day / price_prev * 100 if price_prev else 0

            ema_fast_disp = df_chart["Close"].ewm(span=disp_ema_fast, adjust=False).mean()
            ema_slow_disp = df_chart["Close"].ewm(span=disp_ema_slow, adjust=False).mean()
            ema_fast_now = float(ema_fast_disp.iloc[-1])
            ema_slow_now = float(ema_slow_disp.iloc[-1])
            kairi = (price_now - ema_slow_now) / ema_slow_now * 100 if ema_slow_now else 0
            trend = "上昇トレンド 📈" if ema_fast_now > ema_slow_now else "下降トレンド 📉"

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("現在値", f"{price_now:,.4f}", f"{delta_day:+.4f} ({delta_pct:+.2f}%)")
            m2.metric(f"EMA{disp_ema_fast}", f"{ema_fast_now:,.4f}")
            m3.metric(f"EMA{disp_ema_slow}", f"{ema_slow_now:,.4f}", f"乖離率 {kairi:+.2f}%")
            m4.metric("トレンド", trend)

            fig = make_subplots(
                rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.03,
            )

            fig.add_trace(go.Candlestick(
                x=df_chart.index, open=df_chart["Open"], high=df_chart["High"], low=df_chart["Low"], close=df_chart["Close"],
                name="価格", increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
            ), row=1, col=1)

            fig.add_trace(go.Scatter(x=df_chart.index, y=ema_fast_disp, name=f"EMA{disp_ema_fast}", line=dict(color="#4caf50", width=1.5, dash="dot")), row=1, col=1)
            fig.add_trace(go.Scatter(x=df_chart.index, y=ema_slow_disp, name=f"EMA{disp_ema_slow}", line=dict(color="#9c27b0", width=1.5, dash="dot")), row=1, col=1)

            colors = ["#26a69a" if float(df_chart["Close"].iloc[i]) >= float(df_chart["Open"].iloc[i]) else "#ef5350" for i in range(len(df_chart))]
            fig.add_trace(go.Bar(x=df_chart.index, y=df_chart["Volume"], name="出来高", marker_color=colors, showlegend=False), row=2, col=1)

            fig.update_layout(
                title=f"{selected_label} {interval_label}チャート（{period_label}）",
                xaxis_rangeslider_visible=False, height=550, paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
                font=dict(color="#fafafa"), legend=dict(orientation="h", y=1.02, x=0), margin=dict(l=10, r=10, t=60, b=10),
            )
            fig.update_xaxes(gridcolor="#2d2d2d", showgrid=True)
            fig.update_yaxes(gridcolor="#2d2d2d", showgrid=True)

            st.plotly_chart(fig, use_container_width=True)

            # ─── 下部テクニカル指標（選択式・参考表示のみ。エントリー/エグジット判定には使わない） ───
            indicator_options = ["RSI", "MACD", "RCI", "ストキャスティクス", "ADX", "CCI", "Williams %R", "ATR"]
            selected_indicators = st.multiselect(
                "表示する下部指標を選択：", indicator_options, default=["RSI", "MACD"], key="t2_indicators",
            )

            high_c, low_c, close_c = df_chart["High"], df_chart["Low"], df_chart["Close"]

            def _sub_chart(title: str, height: int = 220):
                f = make_subplots(rows=1, cols=1)
                f.update_layout(
                    title=title, height=height, paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
                    font=dict(color="#fafafa"), legend=dict(orientation="h", y=1.15, x=0),
                    margin=dict(l=10, r=10, t=40, b=10),
                )
                f.update_xaxes(gridcolor="#2d2d2d", showgrid=True)
                f.update_yaxes(gridcolor="#2d2d2d", showgrid=True)
                return f

            if "RSI" in selected_indicators:
                rsi = calc_rsi(close_c)
                f = _sub_chart("RSI(14)")
                f.add_trace(go.Scatter(x=df_chart.index, y=rsi, name="RSI(14)", line=dict(color="#e91e63", width=1.5)))
                f.add_hline(y=70, line=dict(color="#666666", width=1, dash="dot"))
                f.add_hline(y=30, line=dict(color="#666666", width=1, dash="dot"))
                f.update_yaxes(range=[0, 100])
                st.plotly_chart(f, use_container_width=True)

            if "MACD" in selected_indicators:
                macd_line, signal_line, histogram = calc_macd(close_c)
                f = _sub_chart("MACD")
                hist_colors = ["#26a69a" if v >= 0 else "#ef5350" for v in histogram]
                f.add_trace(go.Bar(x=df_chart.index, y=histogram, name="ヒストグラム", marker_color=hist_colors, showlegend=False))
                f.add_trace(go.Scatter(x=df_chart.index, y=macd_line, name="MACD", line=dict(color="#2196f3", width=1.5)))
                f.add_trace(go.Scatter(x=df_chart.index, y=signal_line, name="シグナル", line=dict(color="#ff9800", width=1.5)))
                st.plotly_chart(f, use_container_width=True)

            if "RCI" in selected_indicators:
                rci_short = calc_rci(close_c, RCI_PERIODS["short"])
                rci_mid = calc_rci(close_c, RCI_PERIODS["mid"])
                rci_long = calc_rci(close_c, RCI_PERIODS["long"])
                f = _sub_chart("RCI（3line）")
                f.add_trace(go.Scatter(x=df_chart.index, y=rci_short, name="RCI短期", line=dict(color="#26a69a", width=1.5)))
                f.add_trace(go.Scatter(x=df_chart.index, y=rci_mid, name="RCI中期", line=dict(color="#ff9800", width=1.5)))
                f.add_trace(go.Scatter(x=df_chart.index, y=rci_long, name="RCI長期", line=dict(color="#2196f3", width=1.5)))
                f.add_hline(y=80, line=dict(color="#666666", width=1, dash="dot"))
                f.add_hline(y=-80, line=dict(color="#666666", width=1, dash="dot"))
                f.update_yaxes(range=[-100, 100])
                st.plotly_chart(f, use_container_width=True)

            if "ストキャスティクス" in selected_indicators:
                stoch_k, stoch_d = calc_stochastic(high_c, low_c, close_c)
                f = _sub_chart("ストキャスティクス・スロー")
                f.add_trace(go.Scatter(x=df_chart.index, y=stoch_k, name="%K", line=dict(color="#e91e63", width=1.5)))
                f.add_trace(go.Scatter(x=df_chart.index, y=stoch_d, name="%D", line=dict(color="#2196f3", width=1.5)))
                f.add_hline(y=80, line=dict(color="#666666", width=1, dash="dot"))
                f.add_hline(y=20, line=dict(color="#666666", width=1, dash="dot"))
                f.update_yaxes(range=[0, 100])
                st.plotly_chart(f, use_container_width=True)

            if "ADX" in selected_indicators:
                plus_di, minus_di, adx = calc_adx(high_c, low_c, close_c)
                f = _sub_chart("ADX / +DI / -DI")
                f.add_trace(go.Scatter(x=df_chart.index, y=adx, name="ADX", line=dict(color="#fafafa", width=1.5)))
                f.add_trace(go.Scatter(x=df_chart.index, y=plus_di, name="+DI", line=dict(color="#26a69a", width=1.5)))
                f.add_trace(go.Scatter(x=df_chart.index, y=minus_di, name="-DI", line=dict(color="#ef5350", width=1.5)))
                f.add_hline(y=25, line=dict(color="#666666", width=1, dash="dot"))
                st.plotly_chart(f, use_container_width=True)

            if "CCI" in selected_indicators:
                cci = calc_cci(high_c, low_c, close_c)
                f = _sub_chart("CCI(20)")
                f.add_trace(go.Scatter(x=df_chart.index, y=cci, name="CCI", line=dict(color="#9c27b0", width=1.5)))
                f.add_hline(y=100, line=dict(color="#666666", width=1, dash="dot"))
                f.add_hline(y=-100, line=dict(color="#666666", width=1, dash="dot"))
                st.plotly_chart(f, use_container_width=True)

            if "Williams %R" in selected_indicators:
                willr = calc_williams_r(high_c, low_c, close_c)
                f = _sub_chart("Williams %R")
                f.add_trace(go.Scatter(x=df_chart.index, y=willr, name="%R", line=dict(color="#ff9800", width=1.5)))
                f.add_hline(y=-20, line=dict(color="#666666", width=1, dash="dot"))
                f.add_hline(y=-80, line=dict(color="#666666", width=1, dash="dot"))
                f.update_yaxes(range=[-100, 0])
                st.plotly_chart(f, use_container_width=True)

            if "ATR" in selected_indicators:
                atr = calc_atr(high_c, low_c, close_c)
                f = _sub_chart("ATR(14)")
                f.add_trace(go.Scatter(x=df_chart.index, y=atr, name="ATR", line=dict(color="#4caf50", width=1.5)))
                st.plotly_chart(f, use_container_width=True)

            # ─── ポジション操作（手動エントリー） ───────────
            st.markdown("---")
            st.subheader("📥 ポジション操作")
            watch_row = None
            if not df_watch.empty and "Yahooティッカー" in df_watch.columns:
                matches = df_watch[df_watch["Yahooティッカー"].astype(str).str.strip() == selected_ticker]
                if not matches.empty:
                    watch_row = matches.iloc[0]

            if watch_row is None:
                st.info("ウォッチリストに無い通貨ペア（手動入力）はポジション操作の対象外です。")
            else:
                position_state = str(watch_row.get("ポジション状態", "")).strip()
                entry_price_now = watch_row.get("建値", "")
                current_direction = str(watch_row.get("売買方向", "")).strip() or "ロング"
                if position_state in ("ロング中", "ショート中"):
                    st.write(f"現在のポジション：**{position_state}**（建値: {entry_price_now} ／ 売買方向: {current_direction}）")
                else:
                    st.write("現在のポジション：**ノーポジ**")
                    entry_direction = st.radio(
                        "売買方向を選択：", ["ロング", "ショート"], horizontal=True,
                        index=1 if current_direction == "ショート" else 0, key="t2_entry_direction",
                    )
                    action_label = "ショートでエントリー" if entry_direction == "ショート" else "ロングでエントリー"
                    entry_ref_time = df_chart.index[-1]
                    st.info(
                        f"この操作では、チャート上の最終確定データ（{interval_label}・{entry_ref_time}時点の終値 "
                        f"{price_now:,.4f}）を建値として「{action_label}」を記録します。リアルタイムの約定時刻ではありません。"
                    )
                    if st.button(f"🟢 ここで{action_label}を記録", key="t2_manual_entry"):
                        try:
                            entry_client = init_connection()
                            entry_sheet = entry_client.open("kabu").worksheet("FXウォッチリスト")
                            entry_records = entry_sheet.get_all_records()
                            row_idx = None
                            for i, r in enumerate(entry_records, start=2):
                                if str(r.get("Yahooティッカー", "")).strip() == selected_ticker:
                                    row_idx = i
                                    break
                            if row_idx is None:
                                st.error("Sheets上に該当通貨ペアの行が見つかりませんでした。")
                            else:
                                position_label = "ショート中" if entry_direction == "ショート" else "ロング中"
                                entry_sheet.update(
                                    f"L{row_idx}:N{row_idx}",
                                    [[round(price_now, 4), position_label, entry_direction]],
                                )
                                st.success(
                                    f"{action_label}を記録しました（建値: {price_now:,.4f} ／ 参照時刻: {entry_ref_time}）。"
                                    "画面を更新します。"
                                )
                                get_records.clear()
                                st.rerun()
                        except Exception as e:
                            st.error(f"エントリー記録に失敗しました: {e}")
    else:
        st.info("👆 上の選択欄から通貨ペアを選ぶか、Yahooティッカーを直接入力してください。")

# ═══════════════════════════════════════════
# タブ3：バックテスト
# ═══════════════════════════════════════════
with tab3:
    st.subheader("🔬 バックテスト")
    df_watch = pd.DataFrame(records) if records else pd.DataFrame()

    strategy_choice = st.selectbox("戦略を選択：", ["EMAクロス", "RCI（3line）"], key="t3_strategy")
    direction_choice = st.radio("売買方向：", ["ロング", "ショート"], horizontal=True, key="t3_direction")
    bt_direction = "short" if direction_choice == "ショート" else "long"

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

    col_b1, col_b2 = st.columns([2, 1])

    with col_b1:
        if not df_watch.empty and "Yahooティッカー" in df_watch.columns:
            bt_options = []
            for _, r in df_watch.iterrows():
                ticker = str(r.get("Yahooティッカー", "")).strip()
                name = str(r.get("通貨ペア名", "")).strip()
                if ticker and ticker != "nan":
                    bt_options.append(f"{ticker} {name}")
            bt_manual = st.text_input("Yahooティッカーを直接入力", placeholder="例: USDJPY=X", key="t3_manual")
            if bt_manual.strip():
                bt_ticker = bt_manual.strip()
                bt_label = f"{bt_ticker}（手動入力）"
            elif bt_options:
                bt_chosen = st.selectbox("通貨ペアを選択：", bt_options, key="t3_pair")
                bt_ticker = bt_chosen.split(" ")[0].strip()
                bt_label = bt_chosen
            else:
                bt_ticker, bt_label = "", ""
        else:
            bt_ticker = st.text_input("Yahooティッカーを入力", key="t3_only_manual").strip()
            bt_label = bt_ticker

    with col_b2:
        bt_interval_label = st.selectbox("時間足：", list(FX_INTERVAL_OPTIONS.keys()), index=5, key="t3_interval")
        bt_interval_value = FX_INTERVAL_OPTIONS[bt_interval_label]["interval"]
        bt_available_periods = FX_INTERVAL_OPTIONS[bt_interval_label]["periods"]

    col_b2b, col_b3 = st.columns([1, 1])
    with col_b2b:
        default_idx = bt_available_periods.index("1年") if "1年" in bt_available_periods else 0
        bt_period = st.selectbox("検証期間：", bt_available_periods, index=default_idx, key="t3_period")
        bt_period_value = PERIOD_OPTIONS[bt_period]

    with col_b3:
        ema_label_suffix = "（判定条件）" if strategy_choice == "EMAクロス" else "（乖離率の表示用）"
        fast_ema = st.number_input(f"短期EMA{ema_label_suffix}", min_value=2, max_value=50, value=20, step=1, key="t3_fast")
        slow_ema = st.number_input(f"長期EMA{ema_label_suffix}", min_value=10, max_value=500, value=200, step=5, key="t3_slow")

    col_b4, col_b5 = st.columns(2)
    with col_b4:
        stop_loss_pips = st.number_input("損切りライン（pips・任意、0=無効）", min_value=0.0, max_value=1000.0, value=0.0, step=1.0, key="t3_sl")
    with col_b5:
        take_profit_pips = st.number_input("利確ライン（pips・任意、0=無効）", min_value=0.0, max_value=2000.0, value=0.0, step=1.0, key="t3_tp")

    run_btn = st.button("▶ バックテスト実行", use_container_width=True, type="primary")

    # st.button()はクリックした瞬間のスクリプト実行でのみTrueになるため、
    # トレード詳細のセレクトボックス操作で再実行された際にも結果を表示し続けられるよう
    # session_stateに結果を保持する（保持しないと再実行時に結果ごと消えてしまう）
    if run_btn and bt_ticker:
        with st.spinner(f"{bt_label} のデータでバックテスト中..."):
            try:
                df_bt_chart = load_fx_chart_data(bt_ticker, bt_period_value, bt_interval_value)
            except ValueError:
                df_bt_chart = pd.DataFrame()

        if df_bt_chart.empty:
            st.error("データを取得できませんでした。ティッカーを確認してください。")
            st.session_state.pop("t3_bt_result", None)
        else:
            df_eng = to_engine_df(df_bt_chart)
            pm = pip_multiplier(bt_ticker)
            indicator = "rci" if strategy_choice == "RCI（3line）" else "ema"
            trades_df = build_trades(
                df_eng, fast=fast_ema, slow=slow_ema,
                stop_loss_pct=0, take_profit_pct=0,
                is_fx=True, pip_multiplier=pm, ma_type="ema",
                indicator=indicator, rci_periods=rci_periods,
                stop_loss_pips=stop_loss_pips, take_profit_pips=take_profit_pips,
                direction=bt_direction,
            )
            summary = summarize(trades_df)

            # チャート表示用に指標を付与（小文字OHLC + ma_fast/ma_slow、timeをindexに）
            data_bt = df_eng.copy()
            data_bt["ma_fast"] = data_bt["close"].ewm(span=fast_ema, adjust=False).mean()
            data_bt["ma_slow"] = data_bt["close"].ewm(span=slow_ema, adjust=False).mean()
            if indicator == "rci":
                data_bt["rci_short"] = calc_rci(data_bt["close"], rci_periods["short"])
                data_bt["rci_mid"] = calc_rci(data_bt["close"], rci_periods["mid"])
                data_bt["rci_long"] = calc_rci(data_bt["close"], rci_periods["long"])
            data_bt = data_bt.set_index("time")

            st.session_state["t3_bt_result"] = {
                "trades_df": trades_df, "summary": summary, "data_bt": data_bt,
                "bt_label": bt_label, "fast_ema": fast_ema, "slow_ema": slow_ema, "bt_period": bt_period,
                "bt_interval_label": bt_interval_label,
                "strategy_choice": strategy_choice, "direction_choice": direction_choice,
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
        bt_interval_label_result = result.get("bt_interval_label", "日足")
        strategy_choice_result = result.get("strategy_choice", "EMAクロス")
        direction_choice_result = result.get("direction_choice", "ロング")
        is_rci = strategy_choice_result == "RCI（3line）" and "rci_short" in data_bt.columns

        if summary["total_trades"] > 0:
            s1, s2, s3, s4 = st.columns(4)
            s1.metric("取引回数", f"{summary['total_trades']} 回")
            s2.metric("勝率", f"{summary['win_rate']} %")
            s3.metric("純利益", f"{summary['net_profit']:+.1f} pips")
            s4.metric("最大ドローダウン", f"{summary['max_drawdown']} pips")
        else:
            st.warning(f"この期間・{strategy_choice_result}設定ではトレードが発生しませんでした。")

        if is_rci:
            fig_bt = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.05)
            fig_bt.add_trace(go.Scatter(x=data_bt.index, y=data_bt["close"], name="終値", line=dict(color="#fafafa", width=1)), row=1, col=1)
            fig_bt.add_trace(go.Scatter(x=data_bt.index, y=data_bt["rci_short"], name="RCI短期", line=dict(color="#26a69a", width=1.5)), row=2, col=1)
            fig_bt.add_trace(go.Scatter(x=data_bt.index, y=data_bt["rci_mid"], name="RCI中期", line=dict(color="#ff9800", width=1.5)), row=2, col=1)
            fig_bt.add_trace(go.Scatter(x=data_bt.index, y=data_bt["rci_long"], name="RCI長期", line=dict(color="#2196f3", width=1.5)), row=2, col=1)
            fig_bt.add_hline(y=80, line=dict(color="#ef5350", width=1, dash="dot"), row=2, col=1)
            fig_bt.add_hline(y=-80, line=dict(color="#26a69a", width=1, dash="dot"), row=2, col=1)
            title = f"{bt_label} RCI（3line）バックテスト・{direction_choice_result}（{bt_interval_label_result}・{bt_period}）"
        else:
            fig_bt = go.Figure()
            fig_bt.add_trace(go.Scatter(x=data_bt.index, y=data_bt["close"], name="終値", line=dict(color="#fafafa", width=1)))
            fig_bt.add_trace(go.Scatter(x=data_bt.index, y=data_bt["ma_fast"], name=f"EMA{fast_ema}（短期）", line=dict(color="#ff9800", width=1.5)))
            fig_bt.add_trace(go.Scatter(x=data_bt.index, y=data_bt["ma_slow"], name=f"EMA{slow_ema}（長期）", line=dict(color="#2196f3", width=1.5)))
            title = f"{bt_label} EMA{fast_ema}/EMA{slow_ema} バックテスト・{direction_choice_result}（{bt_interval_label_result}・{bt_period}）"

        if not trades_df.empty:
            entry_row = dict(row=1, col=1) if is_rci else {}
            entry_marker_name = "エントリー（ショート）" if direction_choice_result == "ショート" else "エントリー（ロング）"
            exit_marker_name = "イグジット（買い戻し）" if direction_choice_result == "ショート" else "イグジット（売り）"
            fig_bt.add_trace(go.Scatter(x=trades_df["signal_date"], y=trades_df["entry_price"], mode="markers", name=entry_marker_name, marker=dict(symbol="triangle-down" if direction_choice_result == "ショート" else "triangle-up", size=12, color="#ef5350" if direction_choice_result == "ショート" else "#26a69a")), **entry_row)
            fig_bt.add_trace(go.Scatter(x=trades_df["exit_date"], y=trades_df["exit_price"], mode="markers", name=exit_marker_name, marker=dict(symbol="triangle-up" if direction_choice_result == "ショート" else "triangle-down", size=12, color="#26a69a" if direction_choice_result == "ショート" else "#ef5350")), **entry_row)

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
                col_dsel, col_dbars, col_dheight, col_dwidth = st.columns([2, 1, 1, 1])
                with col_dsel:
                    selected_trade_label = st.selectbox("対象トレードを選択：", trade_labels, key="t3_detail_trade")
                with col_dbars:
                    n_bars = st.slider("前後の余白本数（期間の縮尺）", min_value=1, max_value=50, value=5, step=1, key="t3_detail_nbars")
                with col_dheight:
                    detail_height = st.slider("チャート高さ(px)", min_value=300, max_value=900, value=400, step=50, key="t3_detail_height")
                with col_dwidth:
                    detail_width = st.slider("チャート幅(px)", min_value=400, max_value=1600, value=800, step=50, key="t3_detail_width")

                selected_trade = trade_records.iloc[trade_labels.index(selected_trade_label)].to_dict()
                try:
                    fig_detail = build_trade_detail_figure(
                        data_bt, selected_trade,
                        fast_col="ma_fast", slow_col="ma_slow",
                        n_bars=n_bars,
                        rci_cols=["rci_short", "rci_mid", "rci_long"] if is_rci else None,
                        theme={"height": detail_height, "width": detail_width},
                    )
                    st.plotly_chart(fig_detail, use_container_width=False)
                except Exception as e:
                    st.warning("トレード詳細の表示に失敗しました（再度「▶ バックテスト実行」を押すと直る場合があります）")
                    st.caption(f"data_bt列: {list(data_bt.columns)}")
                    st.exception(e)
