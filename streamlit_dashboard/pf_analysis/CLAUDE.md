# streamlit_dashboard/pf_analysis/ — PF可視化UI

---

## このフォルダの役割

`backtest/` で計算したプロフィットファクター（PF）の結果を
Streamlit上で可視化するダッシュボード。

着手は Phase 2（Phase 1のbacktestエンジン完成後）。
仕様の詳細は `docs/pf_spec.md` の「Phase2 Streamlit UI仕様」を参照。

---

## ファイル構成

```
pf_analysis/
├── CLAUDE.md       # このファイル
└── app_pf.py       # メインのStreamlitアプリ
```

---

## 実装ルール

```
- backtest/results/ のCSVを読み込んで表示する（再計算はしない）
- 既存の app_fx.py / app.py のUIスタイルに合わせる
- パスワード保護は既存と同じ方式（st.secrets["app_password"]）を踏襲
- パッケージ追加は uv add のみ
```

---

## 画面仕様（概要）

**サイドバー**
- 対象：FX / 株 の選択
- ティッカー：テキスト入力
- 時間足：セレクトボックス（1h / 4h / 1d）
- fastEMA / slowEMA：スライダー

**メインエリア**
- KPIカード：PF / 勝率 / 総トレード数 / MDD
- トレード一覧テーブル
- 資産曲線グラフ（Plotly）
- シグナル別損益分布（ヒストグラム）

詳細は `docs/pf_spec.md` を必ず確認すること。

---

## 起動コマンド

```bash
uv run streamlit run streamlit_dashboard/pf_analysis/app_pf.py
```

---

## ステータス

現在 Phase 0（骨組みのみ）。実装は Phase 1完了後に着手する。
