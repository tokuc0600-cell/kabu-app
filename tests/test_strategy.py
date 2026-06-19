from __future__ import annotations

import pandas as pd

from backtest.strategy import (
    CrossType,
    Position,
    PositionState,
    attach_indicators,
    calc_ema,
    calc_sma,
    detect_cross_at,
    detect_cross_series,
    should_enter,
    should_exit,
    step_position,
)


def test_calc_ema_matches_pandas_ewm():
    series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    result = calc_ema(series, period=2)
    expected = series.ewm(span=2, adjust=False).mean()
    pd.testing.assert_series_equal(result, expected)


def test_calc_sma_matches_rolling_mean():
    series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    result = calc_sma(series, period=2)
    expected = series.rolling(window=2).mean()
    pd.testing.assert_series_equal(result, expected)


def test_detect_cross_at_golden():
    assert detect_cross_at(prev_fast=9, prev_slow=10, curr_fast=11, curr_slow=10) == CrossType.GOLDEN


def test_detect_cross_at_dead():
    assert detect_cross_at(prev_fast=11, prev_slow=10, curr_fast=9, curr_slow=10) == CrossType.DEAD


def test_detect_cross_at_none():
    assert detect_cross_at(prev_fast=11, prev_slow=10, curr_fast=12, curr_slow=10) == CrossType.NONE


def test_detect_cross_series_finds_golden_and_dead():
    df = pd.DataFrame({
        "ma_fast": [9, 11, 12, 9, 8],
        "ma_slow": [10, 10, 10, 10, 10],
    })
    cross = detect_cross_series(df)
    assert cross.iloc[0] == CrossType.NONE
    assert cross.iloc[1] == CrossType.GOLDEN
    assert cross.iloc[2] == CrossType.NONE
    assert cross.iloc[3] == CrossType.DEAD


def test_attach_indicators_ema():
    df = pd.DataFrame({"close": [1.0, 2.0, 3.0, 4.0, 5.0]})
    result = attach_indicators(df, fast=2, slow=3, ma_type="ema")
    assert "ma_fast" in result.columns
    assert "ma_slow" in result.columns


def test_should_enter_requires_no_position_and_golden_cross():
    no_pos = Position(state=PositionState.NONE)
    assert should_enter(no_pos, CrossType.GOLDEN) is True
    assert should_enter(no_pos, CrossType.DEAD) is False

    long_pos = Position(state=PositionState.LONG, entry_price=100)
    assert should_enter(long_pos, CrossType.GOLDEN) is False


def test_should_exit_on_stop_loss():
    pos = Position(state=PositionState.LONG, entry_price=100)
    exit_flag, reason = should_exit(pos, CrossType.NONE, current_price=94, stop_loss_pct=5, take_profit_pct=10)
    assert exit_flag is True
    assert reason == "STOP_LOSS"


def test_should_exit_on_take_profit():
    pos = Position(state=PositionState.LONG, entry_price=100)
    exit_flag, reason = should_exit(pos, CrossType.NONE, current_price=111, stop_loss_pct=5, take_profit_pct=10)
    assert exit_flag is True
    assert reason == "TAKE_PROFIT"


def test_should_exit_on_dead_cross():
    pos = Position(state=PositionState.LONG, entry_price=100)
    exit_flag, reason = should_exit(pos, CrossType.DEAD, current_price=101, stop_loss_pct=5, take_profit_pct=10)
    assert exit_flag is True
    assert reason == "DC"


def test_should_exit_prioritizes_stop_loss_when_multiple_conditions_met():
    pos = Position(state=PositionState.LONG, entry_price=100)
    exit_flag, reason = should_exit(pos, CrossType.DEAD, current_price=94, stop_loss_pct=5, take_profit_pct=10)
    assert exit_flag is True
    assert reason == "STOP_LOSS"


def test_should_exit_no_position_returns_false():
    pos = Position(state=PositionState.NONE)
    exit_flag, reason = should_exit(pos, CrossType.DEAD, current_price=100, stop_loss_pct=5, take_profit_pct=10)
    assert exit_flag is False
    assert reason is None


def test_step_position_entry_then_exit():
    pos = Position(state=PositionState.NONE)
    t1 = pd.Timestamp("2026-01-01")
    pos, event = step_position(pos, CrossType.GOLDEN, current_price=100, current_time=t1, stop_loss_pct=5, take_profit_pct=10)
    assert pos.state == PositionState.LONG
    assert pos.entry_price == 100
    assert event["action"] == "ENTRY"

    t2 = pd.Timestamp("2026-01-02")
    pos, event = step_position(pos, CrossType.NONE, current_price=111, current_time=t2, stop_loss_pct=5, take_profit_pct=10)
    assert pos.state == PositionState.NONE
    assert event["action"] == "EXIT"
    assert event["reason"] == "TAKE_PROFIT"


def test_step_position_no_change_when_no_cross_and_no_position():
    pos = Position(state=PositionState.NONE)
    new_pos, event = step_position(pos, CrossType.NONE, current_price=100, current_time=pd.Timestamp("2026-01-01"), stop_loss_pct=5, take_profit_pct=10)
    assert new_pos.state == PositionState.NONE
    assert event is None
