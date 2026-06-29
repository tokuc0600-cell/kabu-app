# 2026-06-30 FXリアルトレード記録：MT4日付フォーマット対応・Gold pip乗数修正

## 概要

前セッションで実装したリアルトレード記録タブ（real_trade_tab.py）で
実際に入力テストをしたところ3つのバグが発覚。すべて修正してプッシュした。

---

## 実際に出した指示

```
MT4の日付表示は、正しくは2026.06.25 02:49:17となっています。この対応はどうすればよい？
```
```
取引評価のボタンをおしたらエラーになりました。
AttributeError: ...
bar = df[mask.values].iloc[-1].copy()
         ^^^^^^^^^^^
```

---

## 起きたこと・気づいたこと

### バグ1：MT4日付（ドット区切り）が変換されない
- MT4のエントリー時刻は `2026.06.25 02:49` または `2026.06.25 02:49:17`（秒付き）の形式
- `broker_to_jst()` は `-` 区切りと `/` 区切りしか対応していなかった
- 実は前セッションの修正で `"%Y.%m.%d %H:%M"` と `"%Y.%m.%d %H:%M:%S"` は追加済みだったため、
  `2026.06.25 02:49:17`（秒付き）はすでに対応していると確認できた

### バグ2：Gold（GC=F）のpip乗数が10000で損益が異常値
- 価格差 5.67 USD × 10000 = 56700 pips → 明らかに誤り
- Gold(XAUUSD/GC=F) の pip は $0.01 単位なので乗数は **100** が正しい
- JPYペア以外はすべて10000にフォールバックしていたのが原因

### バグ3：取引評価ボタンで AttributeError
- `DatetimeIndex <= Timestamp` の比較結果は **numpy.ndarray**（pandasのSeriesではない）
- numpy配列には `.values` 属性がないため `mask.values` で AttributeError が発生した

---

## 原因まとめ

| バグ | 原因 |
|------|------|
| MT4日付 | parse対象フォーマットにドット区切りが未登録（秒付きは実は対応済み） |
| Gold pip乗数 | JPY以外を一律10000にフォールバック。商品先物・Goldを考慮していなかった |
| AttributeError | DatetimeIndex比較→numpy配列。`.values`はpandasオブジェクト専用 |

---

## 直し方

### broker_to_jst() のフォーマット拡張
```python
for fmt in (
    "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M", "%Y/%m/%d %H:%M:%S",
    "%Y.%m.%d %H:%M", "%Y.%m.%d %H:%M:%S",   # MT4形式
):
```

### _infer_pip_multiplier() を新設
```python
def _infer_pip_multiplier(ticker: str, pair_name: str) -> float:
    combined = (ticker + pair_name).upper()
    if any(k in combined for k in ("XAU", "GOLD", "GC=F", "GC=")):
        return 100.0   # Gold: 1pip = $0.01
    if any(k in combined for k in ("XAG", "SILVER", "SI=")):
        return 1000.0
    if "JPY" in combined:
        return 100.0
    return 10000.0
```
フォームにpip乗数のnumber_inputを追加し、自動推定値を初期値として表示・ユーザーが手動変更できるようにした。

### mask.values → mask
```python
# 修正前
bar = df[mask.values].iloc[-1].copy()
bar["_bar_time"] = df[mask.values].index[-1]

# 修正後
bar = df[mask].iloc[-1].copy()
bar["_bar_time"] = df[mask].index[-1]
```

---

## コミット

- `12612ad` — fix: MT4ドット区切り日付対応・Gold/商品先物のpip乗数修正
- `05d81d9` — fix: _find_bar_before_entry のAttributeError修正
