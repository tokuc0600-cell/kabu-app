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


def _add_window_trace(fig, window: pd.DataFrame, point_time, point_price, col: int,
                       fast_col: str, slow_col: str, marker_color: str, marker_symbol: str) -> None:
    fig.add_trace(go.Candlestick(
        x=window.index, open=window["open"], high=window["high"], low=window["low"], close=window["close"],
        name="価格", increasing_line_color="#26a69a", decreasing_line_color="#ef5350", showlegend=False,
    ), row=1, col=col)

    if fast_col in window.columns:
        fig.add_trace(go.Scatter(
            x=window.index, y=window[fast_col], mode="lines", name=fast_col,
            line=dict(color="#ff9800", width=1.5), showlegend=False,
        ), row=1, col=col)

    if slow_col in window.columns:
        fig.add_trace(go.Scatter(
            x=window.index, y=window[slow_col], mode="lines", name=slow_col,
            line=dict(color="#2196f3", width=1.5), showlegend=False,
        ), row=1, col=col)

    fig.add_trace(go.Scatter(
        x=[pd.Timestamp(point_time)], y=[point_price], mode="markers", name="対象点",
        marker=dict(symbol=marker_symbol, size=14, color=marker_color), showlegend=False,
    ), row=1, col=col)


def build_trade_detail_figure(
    data: pd.DataFrame,
    trade: dict,
    fast_col: str = "ema_fast",
    slow_col: str = "ema_slow",
    n_bars: int = 2,
    theme: dict | None = None,
) -> go.Figure:
    """1x2 subplot: 左=エントリー窓、右=エグジット窓。ローソク足+fast/slow MA+対象点マーカー。

    data は open/high/low/close 列（小文字）を持つ前提（backtest/engine.py の to_engine_df() 形式）。
    Streamlit非依存（pd.DataFrame/dict/Figureのみ扱う）。株・FX両方の呼び出し元から使える。
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

    entry_window = get_detail_window(data, entry_time, n_bars)
    exit_window = get_detail_window(data, exit_time, n_bars)

    fig = make_subplots(rows=1, cols=2, subplot_titles=("エントリー周辺", "エグジット周辺"))

    _add_window_trace(fig, entry_window, entry_time, entry_price, col=1,
                       fast_col=fast_col, slow_col=slow_col,
                       marker_color="#26a69a", marker_symbol="triangle-up")
    _add_window_trace(fig, exit_window, exit_time, exit_price, col=2,
                       fast_col=fast_col, slow_col=slow_col,
                       marker_color="#ef5350", marker_symbol="triangle-down")

    theme = theme or {}
    fig.update_layout(
        height=theme.get("height", 350),
        paper_bgcolor=theme.get("paper_bgcolor", "#0e1117"),
        plot_bgcolor=theme.get("plot_bgcolor", "#0e1117"),
        font=dict(color=theme.get("font_color", "#fafafa")),
        margin=dict(l=10, r=10, t=40, b=10),
        xaxis_rangeslider_visible=False,
        xaxis2_rangeslider_visible=False,
    )
    fig.update_xaxes(gridcolor="#2d2d2d", showgrid=True)
    fig.update_yaxes(gridcolor="#2d2d2d", showgrid=True)

    return fig
