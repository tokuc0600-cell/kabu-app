from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def get_detail_window(data: pd.DataFrame, point_time, n_bars: int = 2) -> pd.DataFrame:
    """point_time（エントリー/エグジット時刻）の前後n_bars本を行位置ベースで切り出す。

    時間差ではなく行位置で判定するため、日足/週足/分足いずれでも同じロジックで動く。
    """
    idx = data.index.get_indexer([pd.Timestamp(point_time)], method="nearest")[0]
    start = max(0, idx - n_bars)
    end = min(len(data), idx + n_bars + 1)
    # Copy-on-Writeの遅延ビューのまま列アクセスすると環境によって列解決が不安定になることがあるため、
    # スライス直後に明示的にコピーして実体化させる
    return data.iloc[start:end].copy()


def get_trade_window(data: pd.DataFrame, entry_time, exit_time, margin_bars: int = 5) -> pd.DataFrame:
    """エントリー～エグジットの全期間に、前後margin_bars本の余白を加えて切り出す。"""
    entry_idx = data.index.get_indexer([pd.Timestamp(entry_time)], method="nearest")[0]
    exit_idx = data.index.get_indexer([pd.Timestamp(exit_time)], method="nearest")[0]
    start = max(0, min(entry_idx, exit_idx) - margin_bars)
    end = min(len(data), max(entry_idx, exit_idx) + margin_bars + 1)
    return data.iloc[start:end].copy()


RCI_LINE_STYLES = {
    "rci_short": {"label": "RCI短期", "color": "#26a69a"},
    "rci_mid":   {"label": "RCI中期", "color": "#ff9800"},
    "rci_long":  {"label": "RCI長期", "color": "#2196f3"},
}


def build_trade_detail_figure(
    data: pd.DataFrame,
    trade: dict,
    fast_col: str = "ema_fast",
    slow_col: str = "ema_slow",
    n_bars: int = 5,
    theme: dict | None = None,
    rci_cols: list[str] | None = None,
) -> go.Figure:
    """エントリーからエグジットまでの期間を1本の連続チャートで表示する。

    ローソク足+fast/slow MA+エントリー/エグジットのマーカーを同一チャート上に描画する。
    data は open/high/low/close 列（小文字）を持つ前提（backtest/engine.py の to_engine_df() 形式）。
    Streamlit非依存（pd.DataFrame/dict/Figureのみ扱う）。株・FX両方の呼び出し元から使える。

    rci_colsを指定すると、上段に価格チャート・下段にRCI（短期・中期・長期を重ねて表示、±80ライン付き）の
    2段サブプロットにする（RCI戦略のトレードを拡大表示する際に判定根拠を確認できるようにするため）。
    """
    def _first(*keys):
        for key in keys:
            if key in trade and trade[key] is not None:
                return trade[key]
        return None

    entry_time = _first("エントリー日", "entry_time", "signal_date")
    exit_time = _first("イグジット日", "exit_time", "exit_date")
    entry_price = _first("エントリー値", "entry_price")
    exit_price = _first("イグジット値", "exit_price")

    missing = {"open", "high", "low", "close"} - set(data.columns)
    if missing:
        raise ValueError(f"ローソク足の描画に必要な列が見つかりません: {sorted(missing)}（実際の列: {list(data.columns)}）")

    window = get_trade_window(data, entry_time, exit_time, margin_bars=n_bars)

    available_rci_cols = [c for c in (rci_cols or []) if c in window.columns]
    show_rci = bool(available_rci_cols)
    if show_rci:
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.05)
        price_row = dict(row=1, col=1)
    else:
        fig = go.Figure()
        price_row = {}

    fig.add_trace(go.Candlestick(
        x=window.index, open=window["open"], high=window["high"], low=window["low"], close=window["close"],
        name="価格", increasing_line_color="#26a69a", decreasing_line_color="#ef5350", showlegend=False,
    ), **price_row)

    if fast_col in window.columns:
        fig.add_trace(go.Scatter(
            x=window.index, y=window[fast_col], mode="lines", name=fast_col,
            line=dict(color="#ff9800", width=1.5), showlegend=False,
        ), **price_row)

    if slow_col in window.columns:
        fig.add_trace(go.Scatter(
            x=window.index, y=window[slow_col], mode="lines", name=slow_col,
            line=dict(color="#2196f3", width=1.5), showlegend=False,
        ), **price_row)

    fig.add_trace(go.Scatter(
        x=[pd.Timestamp(entry_time), pd.Timestamp(exit_time)], y=[entry_price, exit_price],
        mode="lines+markers+text", name="エントリー→エグジット",
        line=dict(color="#00e5ff", width=1.5, dash="dash"),
        marker=dict(symbol="circle", size=8, color="#00e5ff"),
        text=["Entry", "Exit"], textposition=["bottom center", "top center"],
        textfont=dict(color="#00e5ff", size=13),
        showlegend=False,
    ), **price_row)

    if show_rci:
        for col in available_rci_cols:
            style = RCI_LINE_STYLES.get(col, {"label": col, "color": "#26a69a"})
            fig.add_trace(go.Scatter(
                x=window.index, y=window[col], mode="lines", name=style["label"],
                line=dict(color=style["color"], width=1.5), showlegend=True,
            ), row=2, col=1)
        fig.add_hline(y=80, line=dict(color="#ef5350", width=1, dash="dot"), row=2, col=1)
        fig.add_hline(y=-80, line=dict(color="#26a69a", width=1, dash="dot"), row=2, col=1)

    theme = theme or {}
    fig.update_layout(
        height=theme.get("height", 400) + (150 if show_rci else 0),
        paper_bgcolor=theme.get("paper_bgcolor", "#0e1117"),
        plot_bgcolor=theme.get("plot_bgcolor", "#0e1117"),
        font=dict(color=theme.get("font_color", "#fafafa")),
        margin=dict(l=10, r=10, t=40, b=10),
        xaxis_rangeslider_visible=False,
    )
    if theme.get("width"):
        fig.update_layout(width=theme["width"])
    fig.update_xaxes(gridcolor="#2d2d2d", showgrid=True)
    fig.update_yaxes(gridcolor="#2d2d2d", showgrid=True)

    return fig
