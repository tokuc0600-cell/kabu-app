# backtest/ — PF分析エンジン

---

## このフォルダの役割

EMAクロスシグナルのプロフィットファクター（PF）を計算するバックテストエンジン。
仕様の詳細は `docs/pf_spec.md` を参照すること。

---

## ファイル構成と役割

```
backtest/
├── CLAUDE.md          # このファイル
├── engine.py          # メインエントリーポイント・PF集計
├── signals.py         # EMAクロスシグナル抽出
├── data_fetcher.py    # yfinanceデータ取得・CSVキャッシュ
├── results/           # バックテスト結果CSV（Git管理対象）
└── data/              # 価格データキャッシュ（.gitignore対象）
```

---

## 実装ルール

### データ取得（data_fetcher.py）
```
- yfinance でOHLCVデータを取得する
- 取得後は data/[ticker]_[timeframe].csv にキャッシュする
- キャッシュが当日分なら再取得しない（APIコール節約）
- data/ フォルダは .gitignore 対象
- パッケージ追加は uv add のみ（pip install禁止）
```

### シグナル抽出（signals.py）
```
- fastEMA と slowEMA を pandas で計算する
- ゴールデンクロス（GC）：前足でfastEMA < slowEMA かつ 当足でfastEMA > slowEMA
- デッドクロス（DC）：前足でfastEMA > slowEMA かつ 当足でfastEMA < slowEMA
- シグナルはDataFrameで返す（signal_date, signal_type, entry_price を含む）
```

### PF計算（engine.py）
```
- イグジットは「次のクロス発生時の始値」（ホールド型）
- FXはpips単位、株は%単位で損益計算
- 出力①：トレード明細CSV（results/YYYYMMDD_[ticker]_[tf]_fast[n]_slow[n].csv）
- 出力②：サマリーCSV（results/YYYYMMDD_summary.csv）に追記
- 出力③：コンソールにサマリーを表示
```

### CLIインターフェース（engine.py）
```bash
# 基本実行
uv run python backtest/engine.py \
  --ticker USDJPY=X \
  --timeframe 4h \
  --fast 20 \
  --slow 200

# オプション一覧
--ticker     : yfinanceティッカー（FX例: USDJPY=X / 株例: 7203.T）
--timeframe  : 1h / 4h / 1d
--fast       : fastEMA期間（デフォルト: 20）
--slow       : slowEMA期間（デフォルト: 200）
--period     : 取得期間（デフォルト: 2y）
--no-cache   : キャッシュを無視して再取得
```

---

## 出力フォーマット

### コンソール出力例
```
========================================
バックテスト結果: USDJPY=X 4h EMA20/200
========================================
総トレード数    : 42
勝率            : 54.8%
プロフィットファクター: 1.73
平均利益        : 48.2 pips
平均損失        : 28.7 pips
リスクリワード比: 1.68
最大ドローダウン: 12.4%
========================================
結果保存: backtest/results/20260619_USDJPY=X_4h_fast20_slow200.csv
```

### CSVカラム定義
```
トレード明細:
  signal_date, signal_type, entry_price, exit_price,
  profit_loss, result, hold_bars

サマリー:
  ticker, timeframe, fast_ema, slow_ema,
  total_trades, win_rate, profit_factor,
  avg_profit, avg_loss, risk_reward, max_drawdown
```

---

## 既存コードとの関係

`market_chart_starter/backtest.py` が元のバックテストスクリプト。
Phase1では以下の方針で進める：

```
1. 既存の backtest.py を壊さない（参照用として残す）
2. backtest/ に新規ファイルとして実装する
3. 既存ロジックで使えるものは import して再利用する
```

---

## Git運用

```bash
# 実装完了後のコミット
git add backtest/
git commit -m "feat: PF計算エンジン実装"

# 結果CSVのコミット（分析のたびに）
git add backtest/results/
git commit -m "data: バックテスト結果 USDJPY=X 4h EMA20/200"
```

---

## note記事との連携

バックテスト完了後、以下をClaude Codeに依頼する：

```
「バックテスト結果（results/の最新CSV）をもとに
 note_workflowのoutlineモードで記事を書いて」
```

→ note_workflow/CLAUDE.md が自動参照されて記事生成・保存まで実行される。
