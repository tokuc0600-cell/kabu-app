"""リアルトレード記録・チャート・評価タブ。

1行 = 1トレード完結（エントリー＋クローズをまとめて記録）の運用前提。
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
import yfinance as yf
import gspread

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backtest.strategy import (
    calc_rsi, calc_macd, calc_rci, calc_stochastic,
    calc_atr, calc_adx, pip_multiplier,
    RCI_PERIODS,
)

# ──────────────────────────────────────────────────────────
# 定数
# ──────────────────────────────────────────────────────────
REAL_SHEET_NAME = "FXリアルトレード履歴"

# 1トレード1行スキーマ
SHEET_HEADERS = [
    "記録日時(JST)", "通貨ペア", "ティッカー", "売買方向",
    "エントリー時刻_MT4", "エントリー時刻_JST",
    "クローズ時刻_MT4", "クローズ時刻_JST",
    "UTC時差",
    "エントリー価格", "クローズ価格", "ロット",
    "損益(pips)", "損切り価格", "利確価格", "メモ",
]

# ブローカーのUTCオフセットプリセット
BROKER_TZ_OPTIONS = {
    "AXIORY / XM / FXGT / Purple Trading など (UTC+2)": 2,
    "AXIORY / XM / FXGT / Purple Trading など 夏時間 (UTC+3)": 3,
    "UTC+0 (GMT / IC Markets等)": 0,
    "UTC+1": 1,
    "UTC+4": 4,
    "カスタム入力": -99,
}

EVAL_INTERVAL_OPTIONS = {
    "4時間足": {"interval": "4h", "period": "6mo"},
    "1時間足": {"interval": "1h", "period": "3mo"},
    "日足":    {"interval": "1d", "period": "1y"},
}

CHART_INTERVAL_OPTIONS = {
    "1時間足": {"interval": "1h", "periods": ["1ヶ月", "2ヶ月", "3ヶ月"]},
    "4時間足": {"interval": "4h", "periods": ["1ヶ月", "3ヶ月", "6ヶ月"]},
    "日足":    {"interval": "1d", "periods": ["3ヶ月", "6ヶ月", "1年"]},
}

PERIOD_MAP = {
    "1ヶ月": "1mo", "2ヶ月": "2mo", "3ヶ月": "3mo",
    "6ヶ月": "6mo", "1年": "1y",
}


# ──────────────────────────────────────────────────────────
# タイムゾーン変換
# ──────────────────────────────────────────────────────────
def broker_to_jst(broker_str: str, utc_offset: int) -> str:
    """ブローカー時刻をJST文字列に変換する。MT4のドット区切り(2026.06.25 14:30)にも対応。"""
    broker_str = broker_str.strip()
    if not broker_str:
        return ""
    for fmt in (
        "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M", "%Y/%m/%d %H:%M:%S",
        "%Y.%m.%d %H:%M", "%Y.%m.%d %H:%M:%S",   # MT4形式
    ):
        try:
            dt = datetime.strptime(broker_str, fmt)
            jst_dt = dt + timedelta(hours=(9 - utc_offset))
            return jst_dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
    return ""


def _infer_pip_multiplier(ticker: str, pair_name: str) -> float:
    """ティッカーまたはペア名からpip乗数を推定する。

    Gold/Silver/商品先物はFXと単位が異なるため個別対応。
    """
    combined = (ticker + pair_name).upper()
    # Gold / XAUUSD / GC=F : 1pip = $0.01 → 乗数100
    if any(k in combined for k in ("XAU", "GOLD", "GC=F", "GC=")):
        return 100.0
    # Silver / XAGUSD : 1pip = $0.001 → 乗数1000
    if any(k in combined for k in ("XAG", "SILVER", "SI=")):
        return 1000.0
    # JPYペア : 1pip = 0.01 → 乗数100
    if "JPY" in combined:
        return 100.0
    # その他FX : 1pip = 0.0001 → 乗数10000
    return 10000.0


def jst_to_chart_x(jst_str: str, interval: str) -> pd.Timestamp | None:
    """JST文字列をチャートx軸値（UTC Timestamp）に変換する。"""
    try:
        ts = pd.Timestamp(jst_str)
    except Exception:
        return None
    if interval in ("1d", "1wk"):
        return ts.normalize()
    return ts - pd.Timedelta(hours=9)  # JST → UTC


# ──────────────────────────────────────────────────────────
# Google Sheets I/O
# ──────────────────────────────────────────────────────────
def _get_or_create_sheet(client) -> gspread.Worksheet:
    spr = client.open("kabu")
    try:
        return spr.worksheet(REAL_SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        sheet = spr.add_worksheet(title=REAL_SHEET_NAME, rows=1000, cols=len(SHEET_HEADERS))
        sheet.append_row(SHEET_HEADERS, value_input_option="USER_ENTERED")
        return sheet


def load_real_history(client) -> pd.DataFrame:
    try:
        spr = client.open("kabu")
        sheet = spr.worksheet(REAL_SHEET_NAME)
        data = sheet.get_all_records()
        return pd.DataFrame(data) if data else pd.DataFrame()
    except gspread.exceptions.WorksheetNotFound:
        return pd.DataFrame()
    except Exception as e:
        st.warning(f"リアルトレード履歴の読み込みに失敗しました: {e}")
        return pd.DataFrame()


def _write_real_trade(client, row: list) -> None:
    sheet = _get_or_create_sheet(client)
    sheet.append_row(row, value_input_option="USER_ENTERED")


# ──────────────────────────────────────────────────────────
# 評価用データ取得・指標計算
# ──────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def _fetch_for_eval(ticker: str, period: str, interval: str) -> pd.DataFrame:
    df = yf.download(ticker, period=period, interval=interval, auto_adjust=True, progress=False)
    if df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
    df.index = pd.to_datetime(df.index)
    return df


def _attach_eval_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c, h, l = df["Close"], df["High"], df["Low"]
    df["ema20"]  = c.ewm(span=20, adjust=False).mean()
    df["ema200"] = c.ewm(span=200, adjust=False).mean()
    df["rsi"] = calc_rsi(c)
    _, _, df["macd_hist"] = calc_macd(c)
    df["rci_short"] = calc_rci(c, RCI_PERIODS["short"])
    df["stoch_k"], df["stoch_d"] = calc_stochastic(h, l, c)
    df["atr"] = calc_atr(h, l, c)
    plus_di, minus_di, adx = calc_adx(h, l, c)
    df["plus_di"], df["minus_di"], df["adx"] = plus_di, minus_di, adx
    return df


def _find_bar_before_entry(df: pd.DataFrame, jst_str: str, interval: str) -> pd.Series | None:
    """エントリー直前の確定足を返す。"""
    try:
        entry_x = jst_to_chart_x(jst_str, interval)
        if entry_x is None:
            return None
    except Exception:
        return None

    idx = df.index
    if hasattr(idx, "tz") and idx.tz is not None:
        idx_cmp   = idx.tz_convert("UTC").tz_localize(None)
        entry_cmp = entry_x.tz_localize(None) if entry_x.tzinfo else entry_x
    else:
        idx_cmp   = idx
        entry_cmp = entry_x

    mask = idx_cmp <= entry_cmp
    if not mask.any():
        return None
    bar = df[mask.values].iloc[-1].copy()
    bar["_bar_time"] = df[mask.values].index[-1]
    return bar


# ──────────────────────────────────────────────────────────
# 指標スコアリング
# ──────────────────────────────────────────────────────────
def _score_indicators(bar: pd.Series, direction: str) -> list[dict]:
    is_long = direction in ("ロング", "long")
    items = []

    def add(name: str, score: int, detail: str, value_str: str = ""):
        label_map = {2: "◎ 有利", 1: "○ やや有利", 0: "△ 中立", -1: "▲ やや不利", -2: "✕ 不利"}
        items.append({"指標": name, "値": value_str,
                       "方向評価": label_map.get(score, "—"), "スコア": score, "コメント": detail})

    rsi = bar.get("rsi")
    if pd.notna(rsi):
        v = f"{float(rsi):.1f}"
        if is_long:
            if rsi < 30:   add("RSI(14)",  2, "売られすぎ圏（ロング好機）", v)
            elif rsi < 40: add("RSI(14)",  1, "やや売られすぎ", v)
            elif rsi > 70: add("RSI(14)", -2, "買われすぎ圏（不利）", v)
            elif rsi > 60: add("RSI(14)", -1, "やや買われすぎ", v)
            else:          add("RSI(14)",  0, "中立域", v)
        else:
            if rsi > 70:   add("RSI(14)",  2, "買われすぎ圏（ショート好機）", v)
            elif rsi > 60: add("RSI(14)",  1, "やや買われすぎ", v)
            elif rsi < 30: add("RSI(14)", -2, "売られすぎ圏（不利）", v)
            elif rsi < 40: add("RSI(14)", -1, "やや売られすぎ", v)
            else:          add("RSI(14)",  0, "中立域", v)

    rci = bar.get("rci_short")
    if pd.notna(rci):
        v = f"{float(rci):.1f}"
        if is_long:
            if rci <= -80:   add("RCI短期",  2, "売られすぎ圏（反転エントリー好機）", v)
            elif rci <= -60: add("RCI短期",  1, "やや売られすぎ", v)
            elif rci >= 80:  add("RCI短期", -2, "買われすぎ圏（不利）", v)
            elif rci >= 60:  add("RCI短期", -1, "やや買われすぎ", v)
            else:            add("RCI短期",  0, "中立域", v)
        else:
            if rci >= 80:    add("RCI短期",  2, "買われすぎ圏（ショートエントリー好機）", v)
            elif rci >= 60:  add("RCI短期",  1, "やや買われすぎ", v)
            elif rci <= -80: add("RCI短期", -2, "売られすぎ圏（不利）", v)
            elif rci <= -60: add("RCI短期", -1, "やや売られすぎ", v)
            else:            add("RCI短期",  0, "中立域", v)

    ema20  = bar.get("ema20")
    ema200 = bar.get("ema200")
    close  = bar.get("Close")
    if pd.notna(ema20) and pd.notna(ema200) and pd.notna(close):
        v = f"EMA20:{float(ema20):.4f} / EMA200:{float(ema200):.4f}"
        if is_long:
            if close > ema20 > ema200:   add("EMAトレンド",  2, "強い上昇トレンド（ロング有利）", v)
            elif close > ema200:         add("EMAトレンド",  1, "中期上昇トレンド", v)
            elif close < ema20 < ema200: add("EMAトレンド", -2, "強い下降トレンド（不利）", v)
            else:                        add("EMAトレンド", -1, "下降トレンド寄り", v)
        else:
            if close < ema20 < ema200:   add("EMAトレンド",  2, "強い下降トレンド（ショート有利）", v)
            elif close < ema200:         add("EMAトレンド",  1, "中期下降トレンド", v)
            elif close > ema20 > ema200: add("EMAトレンド", -2, "強い上昇トレンド（不利）", v)
            else:                        add("EMAトレンド", -1, "上昇トレンド寄り", v)

    macd_hist = bar.get("macd_hist")
    if pd.notna(macd_hist):
        v = f"{float(macd_hist):.5f}"
        if is_long:
            if macd_hist > 0:  add("MACD",  1, "上昇モメンタム（有利）", v)
            elif macd_hist < 0: add("MACD", -1, "下降モメンタム（不利）", v)
            else:               add("MACD",  0, "中立", v)
        else:
            if macd_hist < 0:  add("MACD",  1, "下降モメンタム（ショート有利）", v)
            elif macd_hist > 0: add("MACD", -1, "上昇モメンタム（不利）", v)
            else:               add("MACD",  0, "中立", v)

    stoch_k = bar.get("stoch_k")
    if pd.notna(stoch_k):
        v = f"{float(stoch_k):.1f}"
        if is_long:
            if stoch_k < 20:   add("ストキャスティクス",  2, "売られすぎ（ロング好機）", v)
            elif stoch_k < 30: add("ストキャスティクス",  1, "やや売られすぎ", v)
            elif stoch_k > 80: add("ストキャスティクス", -2, "買われすぎ（不利）", v)
            elif stoch_k > 70: add("ストキャスティクス", -1, "やや買われすぎ", v)
            else:              add("ストキャスティクス",  0, "中立域", v)
        else:
            if stoch_k > 80:   add("ストキャスティクス",  2, "買われすぎ（ショート好機）", v)
            elif stoch_k > 70: add("ストキャスティクス",  1, "やや買われすぎ", v)
            elif stoch_k < 20: add("ストキャスティクス", -2, "売られすぎ（不利）", v)
            elif stoch_k < 30: add("ストキャスティクス", -1, "やや売られすぎ", v)
            else:              add("ストキャスティクス",  0, "中立域", v)

    adx_val  = bar.get("adx")
    plus_di  = bar.get("plus_di")
    minus_di = bar.get("minus_di")
    if pd.notna(adx_val) and pd.notna(plus_di) and pd.notna(minus_di):
        v = f"ADX:{float(adx_val):.1f} +DI:{float(plus_di):.1f} -DI:{float(minus_di):.1f}"
        if adx_val >= 25:
            if is_long and plus_di > minus_di:
                add("ADX/DI",  1, "強いトレンド・+DI優勢（ロング有利）", v)
            elif not is_long and minus_di > plus_di:
                add("ADX/DI",  1, "強いトレンド・-DI優勢（ショート有利）", v)
            else:
                add("ADX/DI", -1, "強いトレンドだが逆向き（不利）", v)
        else:
            add("ADX/DI", 0, f"レンジ相場（ADX={float(adx_val):.1f}）", v)

    atr = bar.get("atr")
    if pd.notna(atr):
        items.append({"指標": "ATR(14)", "値": f"{float(atr):.5f}",
                      "方向評価": "参考値", "スコア": 0, "コメント": "ボラティリティ目安（SL/TP設計に活用）"})

    return items


def _score_to_probability(total: int, maximum: int) -> float:
    if maximum == 0:
        return 0.50
    ratio = max(-1.0, min(1.0, total / maximum))
    return round(0.50 + ratio * 0.22, 3)


# ──────────────────────────────────────────────────────────
# サブタブ1：トレード記録フォーム（1トレード完結記録）
# ──────────────────────────────────────────────────────────
def _render_entry_form(client, fx_watchlist_records: list) -> None:
    st.subheader("✏️ トレード記録")
    st.caption("過去の完結トレードを1行で記録します。エントリー時刻・クローズ時刻をMT4表示のまま入力するとJSTに変換します。")

    # ─── 通貨ペア選択 ───
    df_watch = pd.DataFrame(fx_watchlist_records) if fx_watchlist_records else pd.DataFrame()
    pair_options = []
    if not df_watch.empty and "Yahooティッカー" in df_watch.columns:
        for _, r in df_watch.iterrows():
            ticker = str(r.get("Yahooティッカー", "")).strip()
            name   = str(r.get("通貨ペア名", "")).strip()
            if ticker and ticker != "nan":
                pair_options.append(f"{ticker} {name}")

    col_pair, col_dir = st.columns([3, 1])
    with col_pair:
        manual_ticker = st.text_input("ティッカー直接入力（例: USDJPY=X）", key="rt_manual_ticker")
        if manual_ticker.strip():
            selected_ticker = manual_ticker.strip()
            selected_pair   = selected_ticker
        elif pair_options:
            chosen = st.selectbox("ウォッチリストから選択：", pair_options, key="rt_pair_sel")
            selected_ticker = chosen.split(" ")[0].strip()
            selected_pair   = chosen.split(" ", 1)[1].strip() if " " in chosen else chosen
        else:
            selected_ticker = ""
            selected_pair   = ""
    with col_dir:
        direction = st.radio("売買方向：", ["ロング", "ショート"], horizontal=True, key="rt_dir")

    # ─── ブローカーUTC時差 ───
    st.markdown("##### MT4/MT5 時刻 → JST 変換設定")
    col_tz, col_custom = st.columns([3, 1])
    with col_tz:
        tz_label   = st.selectbox("ブローカーのUTC時差：", list(BROKER_TZ_OPTIONS.keys()), key="rt_tz")
        utc_offset = BROKER_TZ_OPTIONS[tz_label]
    with col_custom:
        if utc_offset == -99:
            utc_offset = st.number_input("UTC時差（例: 2）", min_value=-12, max_value=14, value=2, step=1, key="rt_custom_tz")
    utc_offset = int(utc_offset)

    # ─── エントリー時刻 ───
    st.markdown("##### エントリー")
    col_entry_mt4, col_entry_jst = st.columns(2)
    with col_entry_mt4:
        entry_mt4 = st.text_input(
            "エントリー時刻（MT4・YYYY-MM-DD HH:MM）",
            placeholder="例: 2026-06-27 14:30",
            key="rt_entry_mt4",
        )
    with col_entry_jst:
        entry_jst = broker_to_jst(entry_mt4, utc_offset)
        if entry_jst:
            st.success(f"JST: **{entry_jst}**")
        else:
            st.caption("MT4時刻を入力すると自動変換されます")

    col_ep, col_lot = st.columns(2)
    with col_ep:
        entry_price = st.number_input("エントリー価格", min_value=0.0, format="%.5f", key="rt_entry_price")
    with col_lot:
        lot = st.number_input("ロット数（任意）", min_value=0.0, step=0.01, format="%.2f", key="rt_lot")

    col_sl, col_tp = st.columns(2)
    with col_sl:
        sl_price_raw = st.number_input("損切り価格（任意・0=未設定）", min_value=0.0, format="%.5f", key="rt_sl")
    with col_tp:
        tp_price_raw = st.number_input("利確価格（任意・0=未設定）", min_value=0.0, format="%.5f", key="rt_tp")

    # ─── クローズ時刻 ───
    st.markdown("##### クローズ")
    col_close_mt4, col_close_jst = st.columns(2)
    with col_close_mt4:
        close_mt4 = st.text_input(
            "クローズ時刻（MT4・YYYY-MM-DD HH:MM）",
            placeholder="例: 2026-06-28 09:15",
            key="rt_close_mt4",
        )
    with col_close_jst:
        close_jst = broker_to_jst(close_mt4, utc_offset)
        if close_jst:
            st.success(f"JST: **{close_jst}**")
        else:
            st.caption("MT4時刻を入力すると自動変換されます")

    close_price = st.number_input("クローズ価格", min_value=0.0, format="%.5f", key="rt_close_price")

    # ─── 損益（自動計算 + 手動上書き） ───
    st.markdown("##### 損益")

    _default_pm = int(_infer_pip_multiplier(selected_ticker, selected_pair))
    col_pm, col_pnl_manual = st.columns(2)
    with col_pm:
        custom_pm = st.number_input(
            "pip乗数（JPY=100 / Gold=100 / その他FX=10000）",
            min_value=1, max_value=100000, value=_default_pm, step=1,
            key="rt_pip_multiplier",
            help="Gold(GC=F/XAUUSD)=100、JPYペア=100、EUR/USD等=10000",
        )
    with col_pnl_manual:
        pnl_override_raw = st.number_input("手動入力（上書き・0=自動計算を使用）", step=0.1, format="%.1f", key="rt_pnl_override")

    auto_pnl = None
    if entry_price > 0 and close_price > 0:
        if direction == "ロング":
            auto_pnl = round((close_price - entry_price) * custom_pm, 1)
        else:
            auto_pnl = round((entry_price - close_price) * custom_pm, 1)

    if auto_pnl is not None:
        st.metric(label="自動計算", value=f"{auto_pnl:+.1f} pips")
    else:
        st.caption("エントリー価格とクローズ価格を入力すると自動計算されます")

    pnl_final = pnl_override_raw if pnl_override_raw != 0.0 else (auto_pnl if auto_pnl is not None else "")


    memo = st.text_input("メモ（任意）", key="rt_memo")

    # ─── 記録ボタン ───
    if st.button("💾 トレードを記録する", type="primary", use_container_width=True, key="rt_submit"):
        errors = []
        if not selected_ticker:
            errors.append("通貨ペアが選択されていません。")
        if not entry_jst:
            errors.append("エントリー時刻の形式が正しくありません（YYYY-MM-DD HH:MM）。")
        if not close_jst:
            errors.append("クローズ時刻の形式が正しくありません（YYYY-MM-DD HH:MM）。")
        if entry_price == 0.0:
            errors.append("エントリー価格を入力してください。")
        if close_price == 0.0:
            errors.append("クローズ価格を入力してください。")

        if errors:
            for e in errors:
                st.error(e)
        else:
            now_jst = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            row = [
                now_jst,
                selected_pair, selected_ticker, direction,
                entry_mt4.strip(), entry_jst,
                close_mt4.strip(), close_jst,
                utc_offset,
                round(entry_price, 5), round(close_price, 5),
                lot if lot > 0 else "",
                pnl_final,
                sl_price_raw if sl_price_raw > 0 else "",
                tp_price_raw if tp_price_raw > 0 else "",
                memo,
            ]
            try:
                _write_real_trade(client, row)
                pnl_str = f"{float(pnl_final):+.1f} pips" if pnl_final != "" else "損益未計算"
                st.success(f"✅ トレードを記録しました　{selected_pair} {direction}　{pnl_str}")
            except Exception as e:
                st.error(f"記録に失敗しました: {e}")


# ──────────────────────────────────────────────────────────
# サブタブ2：チャート表示
# ──────────────────────────────────────────────────────────
def _render_chart_tab(client, fx_watchlist_records: list) -> None:
    st.subheader("📈 リアルトレード チャート")

    if st.button("🔄 履歴を再読み込み", key="rt_chart_refresh"):
        _fetch_for_eval.clear()
        st.rerun()

    df_hist = load_real_history(client)

    if df_hist.empty:
        st.info("まだリアルトレード履歴がありません。「トレード記録」タブから登録してください。")
        return

    df_watch = pd.DataFrame(fx_watchlist_records) if fx_watchlist_records else pd.DataFrame()
    watch_options = []
    if not df_watch.empty and "Yahooティッカー" in df_watch.columns:
        for _, r in df_watch.iterrows():
            tk = str(r.get("Yahooティッカー", "")).strip()
            nm = str(r.get("通貨ペア名", "")).strip()
            if tk and tk != "nan":
                watch_options.append(f"{tk} {nm}")

    tickers_in_hist = df_hist["ティッカー"].dropna().unique().tolist() if "ティッカー" in df_hist.columns else []

    col_sel, col_int, col_per = st.columns([2, 1, 1])
    with col_sel:
        manual = st.text_input("ティッカー直接入力（任意）", key="rt_chart_manual")
        if manual.strip():
            chart_ticker = manual.strip()
        elif watch_options:
            chosen = st.selectbox("通貨ペアを選択：", watch_options, key="rt_chart_pair")
            chart_ticker = chosen.split(" ")[0].strip()
        elif tickers_in_hist:
            chart_ticker = st.selectbox("記録済みティッカー：", tickers_in_hist, key="rt_chart_hist_pair")
        else:
            chart_ticker = ""
    with col_int:
        int_label  = st.selectbox("時間足：", list(CHART_INTERVAL_OPTIONS.keys()), key="rt_chart_int")
        int_value  = CHART_INTERVAL_OPTIONS[int_label]["interval"]
        avail_pers = CHART_INTERVAL_OPTIONS[int_label]["periods"]
    with col_per:
        per_label = st.selectbox("表示期間：", avail_pers, key="rt_chart_per")
        per_value = PERIOD_MAP[per_label]

    if not chart_ticker:
        st.info("通貨ペアを選択してください。")
        return

    with st.spinner(f"{chart_ticker} データ取得中..."):
        df_chart = _fetch_for_eval(chart_ticker, per_value, int_value)

    if df_chart.empty:
        st.error(f"「{chart_ticker}」のデータを取得できませんでした。")
        return

    ema20  = df_chart["Close"].ewm(span=20, adjust=False).mean()
    ema200 = df_chart["Close"].ewm(span=200, adjust=False).mean()

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.8, 0.2], vertical_spacing=0.03)
    fig.add_trace(go.Candlestick(
        x=df_chart.index, open=df_chart["Open"], high=df_chart["High"],
        low=df_chart["Low"], close=df_chart["Close"],
        name="価格", increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_chart.index, y=ema20,  name="EMA20",  line=dict(color="#4caf50", width=1.2, dash="dot")), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_chart.index, y=ema200, name="EMA200", line=dict(color="#9c27b0", width=1.2, dash="dot")), row=1, col=1)

    colors_vol = ["#26a69a" if float(df_chart["Close"].iloc[i]) >= float(df_chart["Open"].iloc[i]) else "#ef5350" for i in range(len(df_chart))]
    fig.add_trace(go.Bar(x=df_chart.index, y=df_chart["Volume"], marker_color=colors_vol, name="出来高", showlegend=False), row=2, col=1)

    # トレードマーカー（エントリー △ / クローズ ▽）
    if "ティッカー" in df_hist.columns:
        df_trades = df_hist[df_hist["ティッカー"].astype(str).str.strip() == chart_ticker].copy()
    else:
        df_trades = pd.DataFrame()

    if not df_trades.empty:
        entry_col = "エントリー時刻_JST" if "エントリー時刻_JST" in df_trades.columns else None
        close_col = "クローズ時刻_JST"   if "クローズ時刻_JST"  in df_trades.columns else None
        ep_col    = "エントリー価格"      if "エントリー価格"    in df_trades.columns else None
        cp_col    = "クローズ価格"        if "クローズ価格"      in df_trades.columns else None

        if entry_col and ep_col:
            entry_xs, entry_ys, entry_texts, entry_colors, entry_syms = [], [], [], [], []
            for _, tr in df_trades.iterrows():
                ex = jst_to_chart_x(str(tr[entry_col]), int_value)
                ep = tr.get(ep_col, "")
                if ex is None or str(ep).strip() in ("", "nan"):
                    continue
                ep_f = float(ep)
                d    = str(tr.get("売買方向", "ロング"))
                pnl  = tr.get("損益(pips)", "")
                entry_xs.append(ex)
                entry_ys.append(ep_f)
                entry_syms.append("triangle-down" if d == "ショート" else "triangle-up")
                entry_colors.append("#ef5350" if d == "ショート" else "#26a69a")
                entry_texts.append(f"ENTRY {d}<br>{ep_f:.5f}")
            if entry_xs:
                fig.add_trace(go.Scatter(
                    x=entry_xs, y=entry_ys, mode="markers+text",
                    name="エントリー",
                    marker=dict(symbol=entry_syms, size=14, color=entry_colors, line=dict(width=1, color="#fff")),
                    text=entry_texts, textposition="top center", textfont=dict(size=9),
                ), row=1, col=1)

        if close_col and cp_col:
            close_xs, close_ys, close_texts, close_colors, close_syms = [], [], [], [], []
            for _, tr in df_trades.iterrows():
                cx = jst_to_chart_x(str(tr[close_col]), int_value)
                cp = tr.get(cp_col, "")
                if cx is None or str(cp).strip() in ("", "nan"):
                    continue
                cp_f = float(cp)
                d    = str(tr.get("売買方向", "ロング"))
                pnl  = tr.get("損益(pips)", "")
                close_xs.append(cx)
                close_ys.append(cp_f)
                close_syms.append("triangle-up" if d == "ショート" else "triangle-down")
                close_colors.append("#26a69a" if d == "ショート" else "#ef5350")
                pnl_label = f"<br>{float(pnl):+.1f}pips" if str(pnl).replace("-","").replace(".","").isdigit() else ""
                close_texts.append(f"CLOSE {d}<br>{cp_f:.5f}{pnl_label}")
            if close_xs:
                fig.add_trace(go.Scatter(
                    x=close_xs, y=close_ys, mode="markers+text",
                    name="クローズ",
                    marker=dict(symbol=close_syms, size=14, color=close_colors, line=dict(width=1, color="#fff")),
                    text=close_texts, textposition="bottom center", textfont=dict(size=9),
                ), row=1, col=1)

    fig.update_layout(
        title=f"{chart_ticker} リアルトレード（{int_label}・{per_label}）",
        xaxis_rangeslider_visible=False, height=600,
        paper_bgcolor="#0e1117", plot_bgcolor="#0e1117", font=dict(color="#fafafa"),
        legend=dict(orientation="h", y=1.02, x=0), margin=dict(l=10, r=10, t=60, b=10),
    )
    fig.update_xaxes(gridcolor="#2d2d2d")
    fig.update_yaxes(gridcolor="#2d2d2d")
    st.plotly_chart(fig, use_container_width=True)

    if not df_trades.empty:
        st.markdown("##### このペアのトレード一覧")
        disp_cols = [c for c in [
            "エントリー時刻_JST", "クローズ時刻_JST", "売買方向",
            "エントリー価格", "クローズ価格", "損益(pips)", "メモ",
        ] if c in df_trades.columns]
        st.dataframe(df_trades[disp_cols].iloc[::-1].reset_index(drop=True), use_container_width=True, hide_index=True)


# ──────────────────────────────────────────────────────────
# サブタブ3：トレード評価
# ──────────────────────────────────────────────────────────
def _render_evaluation_tab(client) -> None:
    st.subheader("🏆 エントリー評価")
    st.caption("エントリー時点の各指標状態をスコアリングし、セットアップ品質と推定勝率を算出します。")

    if st.button("🔄 履歴を再読み込み", key="rt_eval_refresh"):
        st.rerun()

    df_hist = load_real_history(client)

    if df_hist.empty:
        st.info("まだリアルトレード履歴がありません。")
        return

    if "エントリー時刻_JST" not in df_hist.columns:
        st.warning("旧形式のデータが含まれています。新規記録したトレードから評価できます。")
        return

    valid = df_hist.dropna(subset=["エントリー時刻_JST", "ティッカー"])
    if valid.empty:
        st.info("評価できるトレードがありません。")
        return

    trade_labels = []
    for _, row in valid.iterrows():
        pnl = row.get("損益(pips)", "")
        pnl_str = f"{float(pnl):+.1f}pips" if str(pnl).replace("-","").replace(".","").isdigit() else "損益未記録"
        label = f"{row.get('エントリー時刻_JST','')} / {row.get('通貨ペア','')}{row.get('ティッカー','')} / {row.get('売買方向','')} / {pnl_str}"
        trade_labels.append(label)

    col_sel, col_int = st.columns([3, 1])
    with col_sel:
        selected_label = st.selectbox("評価するトレードを選択：", trade_labels, key="rt_eval_sel")
    with col_int:
        eval_int_label = st.selectbox("評価用時間足：", list(EVAL_INTERVAL_OPTIONS.keys()), key="rt_eval_int")

    sel_idx    = trade_labels.index(selected_label)
    sel_row    = valid.iloc[sel_idx]
    ticker     = str(sel_row.get("ティッカー", "")).strip()
    entry_jst  = str(sel_row.get("エントリー時刻_JST", "")).strip()
    direction  = str(sel_row.get("売買方向", "ロング")).strip()
    entry_price = sel_row.get("エントリー価格", "")
    close_price = sel_row.get("クローズ価格", "")
    pnl_actual  = sel_row.get("損益(pips)", "")

    eval_cfg = EVAL_INTERVAL_OPTIONS[eval_int_label]

    if st.button("▶ この取引を評価する", type="primary", key="rt_eval_run"):
        with st.spinner(f"{ticker} データ取得・計算中..."):
            df_raw = _fetch_for_eval(ticker, eval_cfg["period"], eval_cfg["interval"])

        if df_raw.empty:
            st.error("データを取得できませんでした。")
            return

        df_ind = _attach_eval_indicators(df_raw)
        bar    = _find_bar_before_entry(df_ind, entry_jst, eval_cfg["interval"])

        if bar is None:
            st.warning(f"エントリー時刻 {entry_jst} に対応するバーが見つかりませんでした。評価用時間足を変えてみてください。")
            return

        score_items = _score_indicators(bar, direction)
        scored      = [s for s in score_items if s["指標"] != "ATR(14)"]
        total_score = sum(s["スコア"] for s in scored)
        max_score   = len(scored) * 2
        prob        = _score_to_probability(total_score, max_score)
        score_pct   = round((total_score / max_score * 50 + 50) if max_score else 50, 1)

        st.markdown(f"### {ticker} {direction}　エントリー: {entry_jst}")

        col_score, col_prob, col_actual = st.columns(3)
        col_score.metric("セットアップ品質スコア", f"{total_score}/{max_score}", f"{score_pct:.0f}%")
        col_prob.metric("推定勝率（指標ベース）", f"{prob*100:.0f}%",
                        help="7指標のアラインメント度合いから算出した目安。実際の勝率の保証ではありません。")

        pnl_str = str(pnl_actual)
        if pnl_str.lstrip("-+").replace(".","").isdigit():
            col_actual.metric("実際の損益", f"{float(pnl_str):+.1f} pips")
        else:
            col_actual.metric("実際の損益", "—")

        # ゲージ
        gauge_fig = go.Figure(go.Indicator(
            mode="gauge+number", value=score_pct, number={"suffix": "%"},
            gauge={
                "axis": {"range": [0, 100]},
                "bar": {"color": "#26a69a" if score_pct >= 60 else "#ff9800" if score_pct >= 45 else "#ef5350"},
                "steps": [
                    {"range": [0, 40],  "color": "#1a1a2e"},
                    {"range": [40, 60], "color": "#16213e"},
                    {"range": [60, 100],"color": "#0f3460"},
                ],
                "threshold": {"line": {"color": "white", "width": 2}, "thickness": 0.75, "value": 50},
            },
            title={"text": "セットアップ品質", "font": {"color": "#fafafa"}},
        ))
        gauge_fig.update_layout(height=250, paper_bgcolor="#0e1117", font=dict(color="#fafafa"), margin=dict(l=20, r=20, t=40, b=10))
        st.plotly_chart(gauge_fig, use_container_width=True)

        # 指標別スコア表
        st.markdown("##### 指標別評価")
        score_df = pd.DataFrame(score_items)[["指標", "値", "方向評価", "スコア", "コメント"]]

        def _color_score(val):
            try:
                v = int(val)
                if v >= 2:  return "color: #26a69a; font-weight:bold"
                if v == 1:  return "color: #4caf50"
                if v == 0:  return "color: #888888"
                if v == -1: return "color: #ff9800"
                if v <= -2: return "color: #ef5350; font-weight:bold"
            except (TypeError, ValueError):
                pass
            return ""

        st.dataframe(score_df.style.map(_color_score, subset=["スコア"]), use_container_width=True, hide_index=True)

        bar_time = bar.get("_bar_time")
        if bar_time is not None:
            st.caption(f"評価に使用した確定足: {bar_time} UTC（{eval_int_label}）")


# ──────────────────────────────────────────────────────────
# サブタブ4：統計
# ──────────────────────────────────────────────────────────
def _render_stats_tab(client) -> None:
    st.subheader("📊 リアルトレード統計")

    if st.button("🔄 統計を更新", key="rt_stats_refresh"):
        st.rerun()

    df_hist = load_real_history(client)

    if df_hist.empty:
        st.info("まだリアルトレード履歴がありません。")
        return

    df_hist["損益(pips)"] = pd.to_numeric(df_hist["損益(pips)"], errors="coerce")
    valid = df_hist.dropna(subset=["損益(pips)"])

    if valid.empty:
        st.info("損益が記録されているトレードがありません。")
        st.dataframe(df_hist.iloc[::-1].reset_index(drop=True), use_container_width=True, hide_index=True)
        return

    wins   = valid[valid["損益(pips)"] > 0]
    losses = valid[valid["損益(pips)"] < 0]
    total_profit = wins["損益(pips)"].sum()
    total_loss   = abs(losses["損益(pips)"].sum())
    pf           = round(total_profit / total_loss, 2) if total_loss > 0 else float("inf")
    win_rate     = round(len(wins) / len(valid) * 100, 1)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("取引数", f"{len(valid)}")
    c2.metric("勝率", f"{win_rate} %")
    c3.metric("PF", f"{pf}")
    c4.metric("純損益", f"{valid['損益(pips)'].sum():+.1f} pips")
    avg_w = f"{wins['損益(pips)'].mean():.1f}" if not wins.empty else "—"
    avg_l = f"{losses['損益(pips)'].mean():.1f}" if not losses.empty else "—"
    c5.metric("平均利益/損失", f"{avg_w} / {avg_l}")

    # 累積損益グラフ
    cum_pnl = valid["損益(pips)"].cumsum().reset_index(drop=True)
    fig_cum = go.Figure()
    last_val = cum_pnl.iloc[-1]
    line_color = "#26a69a" if last_val >= 0 else "#ef5350"
    fig_cum.add_trace(go.Scatter(
        x=list(range(1, len(cum_pnl)+1)), y=cum_pnl,
        mode="lines+markers", name="累積損益",
        line=dict(color=line_color, width=2),
        fill="tozeroy", fillcolor=f"rgba({'38,166,154' if last_val>=0 else '239,83,80'},0.1)",
    ))
    fig_cum.add_hline(y=0, line=dict(color="#666", width=1, dash="dot"))
    fig_cum.update_layout(
        title="累積損益（pips）", xaxis_title="取引番号", yaxis_title="累積損益(pips)",
        height=280, paper_bgcolor="#0e1117", plot_bgcolor="#0e1117", font=dict(color="#fafafa"),
        margin=dict(l=10, r=10, t=40, b=10), xaxis=dict(gridcolor="#2d2d2d"), yaxis=dict(gridcolor="#2d2d2d"),
    )
    st.plotly_chart(fig_cum, use_container_width=True)

    # ペア別成績
    pair_col = next((c for c in ["通貨ペア", "ティッカー"] if c in valid.columns), None)
    if pair_col:
        st.markdown("##### ペア別成績")
        pair_stats = valid.groupby(pair_col).agg(
            取引数=("損益(pips)", "count"),
            純損益=("損益(pips)", "sum"),
            勝率=("損益(pips)", lambda x: round((x > 0).sum() / len(x) * 100, 1)),
        ).reset_index().sort_values("純損益", ascending=False)
        pair_stats["純損益"] = pair_stats["純損益"].round(1)
        st.dataframe(pair_stats, use_container_width=True, hide_index=True)

    # 全履歴
    st.markdown("##### 全トレード一覧")
    disp_cols = [c for c in [
        "エントリー時刻_JST", "クローズ時刻_JST", "通貨ペア", "売買方向",
        "エントリー価格", "クローズ価格", "損益(pips)", "メモ",
    ] if c in df_hist.columns]

    def _c_pnl(val):
        try:
            v = float(val)
            return "color: #26a69a" if v > 0 else "color: #ef5350" if v < 0 else ""
        except (TypeError, ValueError):
            return ""

    disp_df = df_hist[disp_cols].iloc[::-1].reset_index(drop=True)
    styled  = disp_df.style.map(_c_pnl, subset=["損益(pips)"] if "損益(pips)" in disp_cols else [])
    st.dataframe(styled, use_container_width=True, hide_index=True)


# ──────────────────────────────────────────────────────────
# メインエントリーポイント
# ──────────────────────────────────────────────────────────
def render_real_trade_tab(client, fx_watchlist_records: list) -> None:
    """リアルトレードタブ全体をレンダリングする。app_fx.pyから呼び出す。"""
    sub1, sub2, sub3, sub4 = st.tabs(["✏️ トレード記録", "📈 チャート", "🏆 エントリー評価", "📊 統計"])

    with sub1:
        _render_entry_form(client, fx_watchlist_records)

    with sub2:
        _render_chart_tab(client, fx_watchlist_records)

    with sub3:
        _render_evaluation_tab(client)

    with sub4:
        _render_stats_tab(client)
