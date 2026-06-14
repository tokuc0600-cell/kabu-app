# kabu_app プロジェクト

## 概要
FX・日本株の投資分析ツール。
Streamlit + Google Sheets + yfinance を使ったWebダッシュボード。

## フォルダ構成
kabu_app/
├── .streamlit/
│   └── secrets.toml          # ローカル認証情報（gitignore対象）
├── credentials/              # GCPサービスアカウントJSON（gitignore対象）
├── streamlit_dashboard/
│   ├── fx/
│   │   ├── app_fx.py         # FXウォッチリスト Streamlit アプリ（メイン）
│   │   └── sync_fx.py        # FX用 ローカルバッチ同期スクリプト
│   └── stock/
│       ├── app.py            # 日本株ウォッチリスト Streamlit アプリ
│       ├── sync_kabu.py      # 日本株用 ローカルバッチ同期スクリプト
│       ├── requirements.txt  # Streamlit Cloud用パッケージ定義
│       └── .streamlit/       # Streamlit Cloud用設定
├── market_chart_starter/
│   ├── index.html            # ローカルチャートビューア
│   ├── backtest.py           # EMAクロス バックテスト
│   └── sample_4h.csv         # サンプルデータ
├── .gitignore
├── pyproject.toml            # uv パッケージ管理
├── uv.lock                   # uv バージョンロック
└── CLAUDE.md                 # このファイル

## 技術スタック
- Python: 3.11.15
- パッケージ管理: uv 0.11.19
- Webフレームワーク: Streamlit
- データソース: yfinance（Yahoo Finance API）
- データ保存: Google Sheets（「kabu」ワークブック）
- GCP認証: サービスアカウント（gspread）

## 主要機能

### FXウォッチリスト（app_fx.py）
- Google Sheets「kabu」→「FXウォッチリスト」シートを参照
- 通貨ペアの4時間足データを yfinance で取得
- 20EMA・200EMAクロス判定（ゴールデンクロス/デッドクロス）
- パスワード保護付き（st.secrets["app_password"]）
- Streamlit Community Cloudにデプロイ済み・動作確認済み

### 日本株ウォッチリスト（app.py）
- Google Sheets「kabu」→「ウォッチリスト」シートを参照
- 日足データで5日MA・25日MAクロス判定
- ティッカーは「銘柄コード.T」形式（東証）

### バッチ同期（sync_fx.py / sync_kabu.py）
- ローカル実行でGoogle Sheetsを直接更新
- 認証：credentials/フォルダのJSONファイルを使用

### チャートビューア（index.html）
- ブラウザで直接開くローカルツール
- CSVを読み込んでローソク足＋EMAを表示

## 開発ルール
- パッケージ追加は uv add パッケージ名 のみ（pip install禁止）
- Streamlitの起動は uv run streamlit run [ファイルパス]
- APIキー・認証情報は .streamlit/secrets.toml または credentials/ から読む
- credentials/ と .streamlit/secrets.toml はGitに含めない（.gitignore済み）

## ローカル起動コマンド
uv run streamlit run streamlit_dashboard/fx/app_fx.py
uv run streamlit run streamlit_dashboard/stock/app.py
uv run python streamlit_dashboard/fx/sync_fx.py
uv run python streamlit_dashboard/stock/sync_kabu.py
uv run python market_chart_starter/backtest.py market_chart_starter/sample_4h.csv --fast 20 --slow 200

## Google Sheets構成
- ワークブック名：「kabu」
- シート①：「FXウォッチリスト」（通貨ペア名, Yahooティッカー, 現在値, 20EMA, 200EMA, 20EMA乖離率, トレンド状態, シグナル, 最終更新日時）
- シート②：「ウォッチリスト」（銘柄コード, 銘柄名, 現在値, 25日移動平均, 25日乖離率, シグナル）

## 認証フロー
ローカル実行時：st.secrets["gcp_service_account"] → gspread認証
Streamlit Cloud：Cloudのsecretsに設定済み

## 今後の拡張候補
- RSI・MACD等のテクニカル指標追加
- 複数時間足の切替（1時間足・日足）
- GitHub Actions による定時自動同期
- 情報収集の自動化（ニュース・決算情報）
