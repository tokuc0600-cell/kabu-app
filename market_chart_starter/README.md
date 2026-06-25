# market_chart_starter

ローカル保存向けの最小構成です。

## 内容
- `index.html`  
  4時間足CSVを読み込んで、ローソク足 + EMA を表示
- `backtest.py`  
  EMAクロスの簡易バックテスト
- `sample_4h.csv`  
  サンプルデータ

## 使い方
### 1) チャート
`index.html` をブラウザで開く  
CSVを選択すると表示されます

### 2) バックテスト
```bash
python backtest.py sample_4h.csv --fast 20 --slow 200 --out trades_output.csv
```

## CSV形式
`time,open,high,low,close,volume`

## 次の拡張候補
- 複数EMA表示
- ATR / RSI / MACD
- 手数料、スプレッド、スリッページ
- 空売り / ショート
- 日足・1時間足の切替
- 差分更新APIからCSV自動追記
