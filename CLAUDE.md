# kabu_app プロジェクト

最終更新: 2026-06-20

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
│   ├── strategy.py                    # ★エントリー・エグジットの単一定義 ★新規
│   ├── engine.py                      # strategy.pyを呼び出してPF検証
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

## エントリー・エグジット戦略（★最重要・単一情報源）

**課題認識（2026-06-20）**：
これまで `backtest/`（過去データでのPF検証）と `streamlit_dashboard/`（リアルタイムシグナル表示）で
エントリー・エグジットのロジックが別々に実装される構造になっており、両者が連携していなかった。
これにより「バックテストで検証した条件」と「実際に表示されるシグナル」がズレるリスクがあった。

**方針**：
エントリー・エグジット条件は `backtest/strategy.py` に一元定義し、
`backtest/engine.py`（過去検証）と `streamlit_dashboard/fx/app_fx.py` ・ `streamlit_dashboard/stock/app.py`（リアルタイム表示）の
**両方がこの同じモジュールを呼び出す**。ロジックの二重実装を禁止する。

### エントリー条件

- EMAゴールデンクロス発生（**確定足ベース**で判定。リアルタイム未確定足は使わない）
- かつ、現在ノーポジであること（ポジション状態管理を参照）

### エグジット条件（いずれかを満たした時点でエグジット）

1. EMAデッドクロス発生（確定足ベース）
2. 損切りライン到達（建値からの下落率 or 金額が閾値超）
3. 利確ライン到達（建値からの上昇率 or 金額が閾値超）

- 損切り・利確の閾値は **銘柄ごとに個別設定**（全銘柄共通の一律ルールにはしない）
- 閾値は Google Sheets 上で管理する（下記「ポジション・リスク管理列」参照）。
  コード変更なしで運用中に調整できることを優先する。

### ポジション状態管理

- 銘柄ごとに「ノーポジ／ロング中」の状態を保持する（Google Sheetsに記録）
- エントリー時：建値（エントリー価格）とエントリー日時を記録
- エグジット時：ポジション状態をノーポジに戻し、建値をクリア
- 状態を持たないと、シグナルが出続けて二重エントリーになる点に注意

### 時間足選択（優先度：低・後回し可）

- 日足・週足など、UIで時間足を選択できるようにする
- ただし `strategy.py` の関数設計時点で「時間足を引数として受け取る」前提にしておくこと
  （後から時間足対応を追加する際の手戻りを防ぐため）

---

## 開発の絶対ルール

```
1. パッケージ追加は uv add パッケージ名 のみ（pip install禁止）
2. Streamlit起動は uv run streamlit run [ファイルパス]
3. APIキー・認証情報は .streamlit/secrets.toml または credentials/ から読む
4. credentials/ と .streamlit/secrets.toml は Git に含めない（.gitignore済み）
5. backtest/data/ はキャッシュ扱い → .gitignore対象
6. 機能追加後は必ず git commit（メッセージ: "feat: [機能名]"）
7. 機能追加・修正後は、コードの正しさだけで終わらせず、実際にコマンドやアプリを動かして検証する
   （CLIは実際の出力値、Streamlit系はブラウザ/スクリーンショットでの画面表示とコンソールエラーの有無を確認すること。
   検証手順の詳細は docs/operation_manual.md を参照）
8. 機能追加・修正によってツールの起動方法・挙動・既知の問題が変わった場合は、
   その変更内容を docs/operation_manual.md にも反映する（コードとマニュアルを同時に更新し、ズレを放置しない）
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
- シート①：「FXウォッチリスト」（通貨ペア名, Yahooティッカー, 現在値, 20EMA, 200EMA, 20EMA乖離率, トレンド状態, シグナル, 最終更新日時, **損切り%, 利確%, 建値, ポジション状態**）
- シート②：「ウォッチリスト」（銘柄コード, 銘柄名, 現在値, 25日移動平均, 25日乖離率, シグナル, **損切り%, 利確%, 建値, ポジション状態**）

### ポジション・リスク管理列（★新規）

| 列名 | 内容 | 入力方法 |
|------|------|---------|
| 損切り% | 建値からの下落許容率（銘柄ごとに個別設定） | 手入力 |
| 利確% | 建値からの上昇目標率（銘柄ごとに個別設定） | 手入力 |
| 建値 | エントリー時の価格 | エントリー時に自動記録 |
| ポジション状態 | "ノーポジ" or "ロング中" | エントリー・エグジット時に自動更新 |

- 損切り%・利確%は運用しながら銘柄ごとに調整する想定のため、コード側にハードコードしない
- Sheets APIの読み書き回数増加に注意。リアルタイム判定のたびに毎回Sheetsを叩くのではなく、
  既存の `sync_fx.py` / `sync_kabu.py` のバッチ同期の仕組みに乗せる

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
- [x] Phase 2.5：エントリー・エグジットロジック統合（strategy.py一元化）
- [ ] Phase 3：発信ワークフロー確立
- [ ] Phase 4：拡張（RSI・MACD・GitHub Actions）
