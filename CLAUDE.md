# kabu_app プロジェクト

最終更新: 2026-06-19

---

## 概要

FX・日本株の投資分析ツール。
EMAクロスシグナルのプロフィットファクター（PF）分析を中核に、
Streamlit ダッシュボードで可視化する。

開発プロセスは note・X で並走発信する。

---

## フォルダ構成

```
kabu_app/
├── CLAUDE.md                          # このファイル（全体統括）
├── pyproject.toml
├── uv.lock
├── .gitignore
│
├── backtest/                          # PF分析エンジン ★新規
│   └── CLAUDE.md                      # → backtest/CLAUDE.md を参照
│
├── streamlit_dashboard/               # Streamlit UI群
│   ├── fx/
│   │   ├── app_fx.py
│   │   └── sync_fx.py
│   ├── stock/
│   │   ├── app.py
│   │   └── sync_kabu.py
│   └── pf_analysis/                   # PF可視化UI ★Phase2で追加
│       └── CLAUDE.md
│
├── market_chart_starter/              # 既存チャートビューア（維持）
│   ├── index.html
│   ├── backtest.py                    # ※Phase1でbacktest/engine.pyに移植
│   └── sample_4h.csv
│
├── note_workflow/                     # note・X発信ワークフロー
│   └── CLAUDE.md                      # → note_workflow/CLAUDE.md を参照
│
└── docs/                              # 設計ドキュメント
    ├── project_vision.md              # プロジェクト全体計画
    ├── pf_spec.md                     # PF機能仕様書
    └── prompts/                       # 再利用プロンプト保管
```

---

## 技術スタック

- Python: 3.11.15
- パッケージ管理: uv 0.11.19（pip install禁止・uv add のみ）
- Webフレームワーク: Streamlit
- データソース: yfinance（Yahoo Finance API）
- データ保存: Google Sheets（「kabu」ワークブック）
- GCP認証: サービスアカウント（gspread）
- 画像生成: Pillow（note用ヘッダー画像）

---

## 開発の絶対ルール

```
1. パッケージ追加は uv add パッケージ名 のみ（pip install禁止）
2. Streamlit起動は uv run streamlit run [ファイルパス]
3. APIキー・認証情報は .streamlit/secrets.toml または credentials/ から読む
4. credentials/ と .streamlit/secrets.toml は Git に含めない（.gitignore済み）
5. backtest/data/ はキャッシュ扱い → .gitignore対象
6. 機能追加後は必ず git commit（メッセージ: "feat: [機能名]"）
```

---

## ローカル起動コマンド

```bash
# FXウォッチリスト
uv run streamlit run streamlit_dashboard/fx/app_fx.py

# 日本株ウォッチリスト
uv run streamlit run streamlit_dashboard/stock/app.py

# バッチ同期
uv run python streamlit_dashboard/fx/sync_fx.py
uv run python streamlit_dashboard/stock/sync_kabu.py

# バックテスト（既存）
uv run python market_chart_starter/backtest.py market_chart_starter/sample_4h.csv --fast 20 --slow 200

# バックテスト（新エンジン・Phase1以降）
uv run python backtest/engine.py --ticker USDJPY=X --timeframe 4h --fast 20 --slow 200
```

---

## Google Sheets構成

- ワークブック名：「kabu」
- シート①：「FXウォッチリスト」（通貨ペア名, Yahooティッカー, 現在値, 20EMA, 200EMA, 20EMA乖離率, トレンド状態, シグナル, 最終更新日時）
- シート②：「ウォッチリスト」（銘柄コード, 銘柄名, 現在値, 25日移動平均, 25日乖離率, シグナル）

---

## 認証フロー

- ローカル実行時：`st.secrets["gcp_service_account"]` → gspread認証
- Streamlit Cloud：Cloudのsecretsに設定済み

---

## サブCLAUDE.mdへの誘導

| タスク | 参照ファイル |
|--------|------------|
| PF計算・バックテスト開発 | `backtest/CLAUDE.md` |
| Streamlit PF可視化UI | `streamlit_dashboard/pf_analysis/CLAUDE.md` |
| note記事・Xポスト生成 | `note_workflow/CLAUDE.md` |

---

## フェーズ進捗

- [x] Phase 0：設計・環境整備
- [x] Phase 1：バックテストエンジン強化
- [x] Phase 2：Streamlit PF可視化UI
- [ ] Phase 3：発信ワークフロー確立
- [ ] Phase 4：拡張（RSI・MACD・GitHub Actions）
