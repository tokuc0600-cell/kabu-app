# 2026-06-25 バックアップ方針の整理とmarket_chart_starterの壊れたgitlink修正

## 概要
ファイル数が増えてきたことを受け、kabu_app全体のバックアップ・管理方針を整理した。調査の過程で`market_chart_starter`が`.gitmodules`の無い「壊れたgitlink」状態になっており、cloneしても復元されないことが判明し修正した。Google Sheetsの定期スナップショットの必要性についても解説した。

## 実際に出した指示
```
kabu_app内のファイルが増えてきました。これらのファイルのバックアップや管理方法についてアドバイスして
```
```
market_chart_starter/.gitは現在のkabu_appの最初の形態なので、不要です。画像については基本公開済なのであまり重要度は高くありません。（再利用の可能性が極めて低い）
```
```
OKです。今の対応と論点をログに残して「Google Sheetsの定期スナップショット」については必要性がいまいちわからないので詳細を解説して
```

## 起きたこと・気づいたこと
- リポジトリ調査で、`.git`が79MB、`note_workflow/assets`が84MBあることが分かった（記事用画像のバイナリ蓄積が主因）。ただし画像は「公開済・再利用可能性が極めて低い」ためユーザー判断で優先度は低いとされた。
- `market_chart_starter`が`git ls-tree`上で`160000 commit ...`（gitlink/サブモジュール参照）として記録されているにもかかわらず、リポジトリルートに`.gitmodules`が存在しないことが判明。この状態だと**kabu_appを新しい環境にcloneした場合、`market_chart_starter/`は空フォルダになり、`backtest.py`・`index.html`・`README.md`・`sample_4h.csv`が復元されない**（別のGitHubリポジトリ`market_chart_starter`単体には残っているが、本体のバックアップ網からは漏れていた）。
- Google Sheets（ポジション状態・建値・エントリー日時等の運用中データ）は、gitにもバックアップされておらず、Googleの変更履歴機能はあるが特定行の過去値をプログラム的に取り出すのが難しく、保持期間にも実務上の限界がある。

## 原因
- `market_chart_starter`は元々独立したgitリポジトリ（`https://github.com/tokuc0600-cell/market_chart_starter`）として作られ、それをkabu_appのディレクトリ内にそのままコピーした結果、ネストした`.git`を持つフォルダになっていた。`git add`した際に内部の`.git`がgitに検出され、通常ファイルではなく「サブモジュール参照（gitlink）」として記録されてしまった。`.gitmodules`を作る正式なサブモジュール登録の手順を踏んでいなかったため、参照だけが残り実体が伴わない状態になっていた。
- Sheetsの運用データが無防備なのは、そもそも「コードで再生成できないデータ」という認識がこれまで明文化されていなかったため（バックアップ対象の判断軸にこのケースが含まれていなかった）。

## 直し方
1. `market_chart_starter/.git`を削除（別リポジトリの履行・履歴自体は失われない。GitHub上の`market_chart_starter`リポジトリはそのまま残る）。
2. `git rm --cached market_chart_starter`でgitlink参照を解除し、`backtest.py`・`index.html`・`README.md`・`sample_4h.csv`をkabu_app本体に通常ファイルとして`git add`・commit・push。これでclone時にも確実に復元されるようになった。
3. Google Sheetsの定期スナップショットについては、`sync_kabu.py`/`sync_fx.py`が既に`sheet.get_all_records()`でシート全体を毎回読んでいるため、そのタイミングでCSVとして保存するだけで追加のAPI呼び出しコストなく実現できる、という設計方針を解説（実装は今回は行わず、次回sync系のコードに触るタイミングで合わせて追加する方針に留めた）。

## トラブルの詳細
特になし（調査ベースの修正で、想定外の挙動は発生しなかった）。

→ 未反映（記事化のタイミングで読み込んで書き起こす。「サブモジュール参照が.gitmodules無しで残ると復元されない」という具体的な学びは、Tipsとして単独の節にもできそう）
