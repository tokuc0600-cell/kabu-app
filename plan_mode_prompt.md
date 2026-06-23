# Plan modeに貼り付けるプロンプト

以下をそのままClaude Code（Plan mode）に貼り付けてください。
事前にCLAUDE.mdの更新版を読み込ませた状態（同じセッション内）で実行するのがベストです。

---

CLAUDE.mdの「エントリー・エグジット戦略」セクションを読んだ上で、
現状の `backtest/` と `streamlit_dashboard/` のコードを確認してください。

確認してほしいこと：

1. `backtest/engine.py`（または `market_chart_starter/backtest.py`）に、
   現在どのようなエントリー・エグジットロジックが実装されているか
2. `streamlit_dashboard/fx/app_fx.py` と `streamlit_dashboard/stock/app.py` に、
   現在どのようなシグナル判定ロジックが実装されているか
3. 上記2つが、ロジックとして一致しているか、ズレているか

その上で、以下の設計に向けた実装計画を提案してください（まだコードは書かないでください）：

- `backtest/strategy.py` を新規作成し、エントリー・エグジット判定ロジックを一元化する
  - エントリー：EMAゴールデンクロス（確定足）かつノーポジ
  - エグジット：デッドクロス OR 損切りライン到達 OR 利確ライン到達（いずれか）
  - 損切り・利確の閾値は銘柄ごとに異なる値を引数として受け取れる関数設計にする
  - 時間足（timeframe）も引数として受け取れる設計にする（今回は未使用でも良いが、後から渡せる形にする）
- `backtest/engine.py` を `strategy.py` を呼び出す形にリファクタリングする
- `streamlit_dashboard/fx/app_fx.py` と `streamlit_dashboard/stock/app.py` も同様に `strategy.py` を呼び出す形にする
- Google Sheetsの「ウォッチリスト」「FXウォッチリスト」シートに
  「損切り%」「利確%」「建値」「ポジション状態」列を追加する想定で、
  読み書きのコードをどう変更する必要があるか
- 既存の `sync_fx.py` / `sync_kabu.py` のバッチ同期の仕組みとどう統合するか

提案は、影響範囲が大きい変更（既存ファイルの破壊的変更を伴う部分）と、
追加のみで済む変更を分けて説明してください。
また、最初の一歩として着手すべき最小単位のタスクも提示してください。
