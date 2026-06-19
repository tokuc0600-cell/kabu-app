import re
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="PF分析ダッシュボード", layout="wide")

RESULTS_DIR = Path(__file__).parent.parent.parent / "backtest" / "results"
DETAIL_PATTERN = re.compile(r"^(?P<date>\d{8})_(?P<ticker>.+)_(?P<timeframe>1h|4h|1d)_fast(?P<fast>\d+)_slow(?P<slow>\d+)\.csv$")


def check_password():
    if "app_password" not in st.secrets:
        st.warning("⚠️ デバッグ情報: Secretsに `app_password` が見つかりません。パスワード保護をスキップします。")
        return True

    def password_entered():
        if st.session_state["password"] == st.secrets["app_password"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
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
    return True


if not check_password():
    st.stop()

st.title("📈 PF分析ダッシュボード")


@st.cache_data(ttl=60)
def list_results() -> pd.DataFrame:
    rows = []
    for path in RESULTS_DIR.glob("*.csv"):
        m = DETAIL_PATTERN.match(path.name)
        if not m:
            continue
        ticker = m.group("ticker")
        rows.append({
            "date": m.group("date"),
            "ticker": ticker,
            "asset": "FX" if "=X" in ticker else "株",
            "timeframe": m.group("timeframe"),
            "fast": int(m.group("fast")),
            "slow": int(m.group("slow")),
            "path": path,
        })
    return pd.DataFrame(rows)


@st.cache_data(ttl=60)
def load_trades(path: str) -> pd.DataFrame:
    return pd.read_csv(path)


results = list_results()

if results.empty:
    st.info("backtest/results/ にバックテスト結果がありません。先に `uv run python -m backtest.engine` を実行してください。")
    st.stop()

st.sidebar.header("🔍 表示条件")

asset = st.sidebar.selectbox("対象", sorted(results["asset"].unique()))
asset_df = results[results["asset"] == asset]

ticker = st.sidebar.selectbox("ティッカー", sorted(asset_df["ticker"].unique()))
ticker_df = asset_df[asset_df["ticker"] == ticker]

timeframe = st.sidebar.selectbox("時間足", sorted(ticker_df["timeframe"].unique()))
tf_df = ticker_df[ticker_df["timeframe"] == timeframe]

combo_options = sorted(set(zip(tf_df["fast"], tf_df["slow"])))
fast, slow = st.sidebar.selectbox(
    "EMA設定（fast/slow）",
    combo_options,
    format_func=lambda c: f"{c[0]} / {c[1]}",
)

combo_df = tf_df[(tf_df["fast"] == fast) & (tf_df["slow"] == slow)]
latest_row = combo_df.sort_values("date").iloc[-1]

trades = load_trades(str(latest_row["path"]))
unit = "pips" if asset == "FX" else "%"

if trades.empty:
    st.warning("この条件のトレードがありません。")
    st.stop()

total_trades = len(trades)
wins = trades.loc[trades["profit_loss"] > 0, "profit_loss"]
losses = trades.loc[trades["profit_loss"] < 0, "profit_loss"]
win_rate = round((trades["result"] == "WIN").mean() * 100, 2)
profit_factor = round(wins.sum() / abs(losses.sum()), 2) if len(losses) and losses.sum() != 0 else float("inf")

equity_curve = trades["profit_loss"].cumsum()
max_drawdown = round((equity_curve.cummax() - equity_curve).max(), 2)

st.subheader(f"📊 {ticker} {timeframe} EMA{fast}/{slow}")

col1, col2, col3, col4 = st.columns(4)
col1.metric("プロフィットファクター", profit_factor)
col2.metric("勝率", f"{win_rate}%")
col3.metric("総トレード数", total_trades)
col4.metric("最大ドローダウン", f"{max_drawdown} {unit}")

st.markdown("#### 資産曲線")
equity_df = pd.DataFrame({"trade_no": range(1, len(equity_curve) + 1), "cumulative_profit_loss": equity_curve})
fig_equity = px.line(equity_df, x="trade_no", y="cumulative_profit_loss", labels={"cumulative_profit_loss": f"累積損益（{unit}）", "trade_no": "トレード回数"})
st.plotly_chart(fig_equity, use_container_width=True)

st.markdown("#### シグナル別損益分布")
fig_hist = px.histogram(trades, x="profit_loss", color="signal_type", barmode="overlay", labels={"profit_loss": f"損益（{unit}）"})
st.plotly_chart(fig_hist, use_container_width=True)

st.markdown("#### トレード一覧")
st.dataframe(trades, use_container_width=True, hide_index=True)
