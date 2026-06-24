# kabu_app 運用マニュアル

最終更新: 2026-06-21
（本マニュアルの内容は実際に各ツールを起動・実行して確認した結果に基づく）

---

## 1. 全体構成と起動コマンド

| ツール | 役割 | 起動コマンド |
|--------|------|------------|
| FXウォッチリスト画面 | Sheets「FXウォッチリスト」の表示・スクリーニング | `uv run streamlit run streamlit_dashboard/fx/app_fx.py` |
| 株ウォッチリスト画面 | Sheets「ウォッチリスト」の表示 | `uv run streamlit run streamlit_dashboard/stock/app.py` |
| PF分析ダッシュボード | `backtest/results/`のCSVを可視化（再計算なし） | `uv run streamlit run streamlit_dashboard/pf_analysis/app_pf.py` |
| FX同期バッチ | yfinance→Sheets「FXウォッチリスト」を上書き更新 | `uv run python streamlit_dashboard/fx/sync_fx.py` |
| 株同期バッチ | yfinance→Sheets「ウォッチリスト」を上書き更新 | `uv run python streamlit_dashboard/stock/sync_kabu.py` |
| バックテスト（単体） | 1銘柄・1設定でPFを計算しCSV保存 | `uv run python -m backtest.engine --ticker USDJPY=X --timeframe 4h --fast 20 --slow 200 --period 2y` |
| バックテスト（一括） | Sheetsの全銘柄を既定EMA設定で一括計算 | `uv run python -m backtest.batch_run --period 2y` |
| エグジット通知チェック | ロング中銘柄が損切/利確閾値（固定%）に到達したらメール通知 | `uv run python scripts/check_exit_signals.py --mode intraday`（または`--mode close`） |

---

## 2. 実際に動かして確認した挙動

### 2.1 FXウォッチリスト画面（app_fx.py）

- 起動直後は通貨ペアの選択が空のため、テーブルは「該当通貨ペア: 0件」と表示される（仕様通り。バグではない）。
- 通貨ペアを1つ選択すると、Sheetsの実データ（現在値・20EMA・200EMA・乖離率・トレンド・シグナル・最終更新日時）が正しく表示されることを確認した。
- 画面上部に「Secretsにapp_passwordが見つかりません」という警告が**常に**出る（詳細は3.1）。

### 2.2 株ウォッチリスト画面（app.py）

- こちらは起動直後にパスワード入力画面（ログイン）が出る。app_fx.pyとは挙動が異なる（詳細は3.1）。
- **2026-06-21: 修正済み。** ファイル先頭にあった `os.system("pip install plotly yfinance")` 相当の行（プロジェクトの絶対ルール「pip install禁止・uv addのみ」に違反するレガシーコード）を削除した。`plotly`・`yfinance`は`pyproject.toml`の依存に既に含まれているため、削除による動作影響は無いことを確認済み。

### 2.3 PF分析ダッシュボード（app_pf.py）

- `backtest/results/`にCSVが無い状態で起動すると「結果がありません」と表示され、エンジン実行を促すメッセージが出る（想定通り）。
- 対象（FX/株）→ティッカー→時間足→EMA設定の順にサイドバーで絞り込み、KPIカード・資産曲線・損益分布・トレード一覧が表示されることを確認した。
- **このUIはバックテストを再計算しない。** 新しい銘柄・設定の結果を見るには、先に`engine.py`または`batch_run.py`を実行してCSVを生成しておく必要がある。

### 2.4 FX同期バッチ（sync_fx.py）

- 実行すると本番のGoogle Sheets「kabu」を実際に書き換える（今回の検証で実際に実行・反映済み）。
- **2026-06-20: Phase 2.5でロジックを`backtest/strategy.py`呼び出しに統一し、書き込み方式も1ペアあたり9回の`update_cell`から2回の`batch_update`（C:I列・L:M列）に変更した。** 旧実装で発生していた429クォータエラー（30ペア中16ペアで書き込み停止）は、API呼び出し回数の大幅削減により軽減される見込み。1ペアでの動作確認は完了済みだが、全銘柄一括実行時に429が再発しないかは要観察。

### 2.5 株同期バッチ（sync_kabu.py）

- 実行して全銘柄（約37件）が正常に完了することを確認した（429エラーは発生しなかった）。
- 2026-06-20: Phase 2.5で`backtest/strategy.py`呼び出しに統一。書き込みはD:G列とJ:K列（建値・ポジション状態）への`batch_update`2回/銘柄に変更（元々1回だったため呼び出し数は+1）。
- 2026-06-21: 各行のデータ取得日時を可視化する機能を追加。書き込み範囲を`J:K`→`J:L`に拡張し、L列に取得時点のタイムスタンプ（`%Y-%m-%d %H:%M`、サーバーのローカル時刻基準）を書き込むようにした。**Sheets「ウォッチリスト」シートのL1セルに手動で「最終更新日時」という見出しを入力しておくこと。** `sheet.get_all_records()`はヘッダー行の文言をキーにして辞書化するため、見出しが無いとapp.py側でこの列が表示されない。

### 2.7 株ウォッチリスト画面（app.py）チャート分析タブの拡張（2026-06-21）

- タブ2「チャート分析」に時間足セレクト（日足/週足/1時間足/15分足）を追加した。yfinanceの制約（分足は直近60日、1時間足は直近730日まで）に合わせ、選んだ時間足によって「表示期間」の選択肢自体が絞り込まれる（制約超えの組み合わせは選択肢に出さない設計のため、エラー表示は基本発生しない）。
- 同タブに表示専用のEMA期間入力（短期/長期、デフォルト20/75）を追加。既存のMA5/MA25（SMA、Sheetsの「ウォッチリスト」シート由来ではなくyfinanceから都度計算）はそのまま残し、EMAは追加の重ね描きとした。**この表示用EMAは`backtest/strategy.py`のロジックやSheetsのEMA設定とは完全に独立しており、バックテスト・シグナル判定には一切影響しない。**

### 2.8 Phase B: エグジット判定の分離・自動通知基盤（2026-06-21）

- `backtest/strategy.py`に表示専用の指標計算関数`calc_rsi()`・`calc_macd()`を追加（エントリー/エグジット判定には使わない）。`backtest`・ライブ画面・通知スクリプトのどこからでも同じ関数を呼べる。
- `backtest/strategy.py`に通知専用のエグジット判定`check_exit_by_pct(entry_price, current_price)`と、その既定閾値の定数`STOP_LOSS_PCT=5.0`・`TAKE_PROFIT_PCT=10.0`を追加した。**これはSheetsの銘柄ごとの損切%・利確%とは別の、全銘柄一律の通知専用ルール。** 既存の`should_exit()`はこの関数に内部委譲する形にリファクタリングしたが、呼び出し元（`engine.py`/`sync_fx.py`/`sync_kabu.py`）は常に明示的に銘柄ごとの%を渡しているため、既存の挙動への影響はない（`uv run python -m backtest.engine --ticker USDJPY=X --timeframe 4h --fast 20 --slow 200 --stop-loss 2 --take-profit 5`で再検証し、レグレッション無しを確認済み）。
- `streamlit_dashboard/stock/app.py`のタブ2「チャート分析」に、RSI(14)・MACD（ヒストグラム・MACD線・シグナル線）の参考表示を追加した（自動判定なし、表示専用）。
- 同タブに「📥 ポジション操作」セクションを追加。選択銘柄がノーポジの場合のみ「エントリーを記録」ボタンが表示され、押すとSheetsのJ:K列（建値・ポジション状態）に直接書き込む。既存の自動エントリー（sync実行時のゴールデンクロス検知）とは独立した経路だが、書き込み先の列が同じため競合しない（手動エントリー後はポジション状態が「ロング中」になり、`should_enter`のノーポジ条件を満たさなくなるため自動エントリーは発火しない）。
- `scripts/check_exit_signals.py`を新規作成。「ウォッチリスト」シートでロング中の銘柄を抽出し、yfinanceで現在値を取得、`check_exit_by_pct()`で損切/利確の固定%判定を行い、該当銘柄をメール通知する。Sheetsへの書き込み・重複通知防止は行わない（要件通り）。対象は株のみ。
- `.github/workflows/check_exit_signals.yml`を新規作成。平日14:00 JST（5:00 UTC）・15:30 JST（6:30 UTC）の2回cron実行。`github.event.schedule`の値で当日中決済（intraday）／翌営業日決済（close）のメール文面を切り替える。
- 認証情報の安全確認：`credentials/`・`.streamlit/secrets.toml`は変更していない。秘密情報はコードに一切書かず、すべて環境変数（GitHub Secrets）経由。`git diff`でも平文の秘密情報が混入していないことを確認済み。

### 2.8.1 メール通知の送信方式変更：Gmail SMTP → Resend API（2026-06-24）

- **背景**：GCPサービスアカウント鍵の漏洩対応（`.streamlit/secrets.toml`のGit追跡除外、鍵のローテーション）後、`check_exit_signals.py`がGitHub Actions上で`google.auth.exceptions.RefreshError: Invalid JWT Signature`で落ちるようになった。原因は鍵ローテーション後も`credentials/`配下のJSONファイルが古い鍵のままだったこと。新鍵に更新して解消。
- その後、Gmail SMTP（`smtplib`）でのメール送信が`smtplib.SMTPAuthenticationError: (535, ... BadCredentials)`で失敗する別問題が発生。ローカル実行では同一のGmailアドレス・アプリパスワードでログイン成功するのに、GitHub Actions上では再現性をもって失敗することから、**GoogleがGitHub ActionsのIP（データセンターIP）からのSMTPログインを拒否している**と判断した。
- 対処として、Gmail SMTP直接送信を廃止し、**Resend（https://resend.com）のメール送信APIを`requests`でHTTP呼び出しする方式に変更**した。`smtplib`・`email.mime.text.MIMEText`への依存を削除。
- Resend無料プラン（送信元ドメイン未認証）の制約により、送信元は`onboarding@resend.dev`固定、**送信先（`NOTIFY_TO`）はResendアカウント登録時のメールアドレスのみ**に限定される。
- **GitHub Secretsの変更**：`GMAIL_ADDRESS`・`GMAIL_APP_PASSWORD`は不要になり削除可（残しておいても実害なし）。新たに**`RESEND_API_KEY`**（ResendダッシュボードのAPI Keysで発行）の登録が必要。`NOTIFY_TO`・`GCP_SERVICE_ACCOUNT_JSON`はそのまま流用。
- ローカル実行（`uv run python scripts/check_exit_signals.py --mode intraday`）時、Google Sheets APIへの接続で`SSLError: CERTIFICATE_VERIFY_FAILED`が発生する場合があるが、これはローカルPC環境側（プロキシ等によるSSL検証の問題）に起因するものでGitHub Actions上では発生しない。動作確認は基本的にGitHub Actions側のworkflow_dispatch手動実行で行う。

### 2.8.2 ウォッチリストUI統一・FXバックテストpips化・RCIトレード詳細パネル（2026-06-24）

- **背景**：FXのウォッチリストを株側に合わせて整理する過程で、FXバックテスト（タブ3）の損切/利確が「%入力」になっており、USDJPYのようなJPYペアでは1%が約150pips相当になってしまい、現実的な損切/利確設定ができていないことが判明した。一方、ライブ運用側（`sync_fx.py`の自動エグジット判定）は元々pips基準（Sheetsの「損切りpips」「利確pips」列）で正しく動いていたため、**バックテスト側だけが取り残されていた**。
- **`backtest/engine.py` `build_trades()`** に`stop_loss_pips`/`take_profit_pips`引数を追加。`is_fx=True`の場合のみ`strategy.step_position()`を`mode="pips"`で呼ぶようにした。`is_fx=False`（株）は従来通り`mode="pct"`で無変更。
- **FXダッシュボード（`app_fx.py`）バックテストタブ**：損切/利確の入力欄を「%」表記から「pips」表記に変更（例: 「損切りライン（pips・任意、0=無効）」）。株側の入力は%のまま変更なし。
- **トレード詳細（ズーム）表示にRCIパネルを追加**：`backtest/detail_view.py build_trade_detail_figure()`に`rci_col`引数を追加し、RCI戦略のトレードを選んだ時は価格+EMA（上段）とRCI±80ライン（下段）の2段サブプロットで表示されるようにした（株・FX両方）。EMAクロス戦略のトレードでは従来通り単一チャート。
- **ウォッチリスト一覧（タブ1）の列構成を統一**：従来の「名称・現在値・シグナル」3列に「トレンド」列を追加し4列に統一。
  - FX：Sheetsの「トレンド状態」列（強い上昇/やや上昇/やや下降/強い下降）をそのまま表示列に追加。Sheetsスキーマの変更なし。
  - 株：Sheetsスキーマは変更せず、`app.py`側で「25日乖離率」の数値から同じ4段階のトレンドラベルをクライアント側で計算して表示（`trend_from_kairi()`、閾値±3%で「強い」/「やや」を判定）。
  - 行選択時の詳細表示からEMA数値・乖離率などの生の指標値を削除し、ポジション状態・建値・最終更新日時（株は業種も）のみに絞った。EMA・RCIなどの指標数値はチャート分析タブ・バックテストタブでのみ確認する運用にした。
- **動作確認**：合成OHLCデータで`build_trades()`のFX pips判定（STOP_LOSS発火）・RCI戦略・株%判定（無変更）・`build_trade_detail_figure()`のRCIサブプロット生成をPythonスクリプトで直接検証済み。Streamlit画面上でのSheets実データを使った目視確認は未実施（次回ブラウザ確認推奨）。
- **既知の問題（今回の変更とは無関係の既存バグ）**：`uv run python -m backtest.engine --help`が`ValueError: unsupported format character`で失敗する。`--stop-loss`/`--take-profit`のヘルプ文字列に含まれる`%`が原因（argparseの`%`書式展開と衝突）。今回の変更前から存在しており、`--help`以外の通常実行には影響しない。

### 2.8.3 バックテストの損切/利確判定をintrabar（高値・安値）方式に修正（2026-06-24）

- **発見の経緯**：上記2.8.2でFXバックテストをpips化した直後、GBPJPY・1時間足・損切30pips/利確60pips設定で最大ドローダウンが715.8pipsという、設定値から想像しにくい大きな値になる不具合が報告された。
- **原因**：`build_trades()`のループが、各バーの**終値のみ**で損切/利確の到達を判定していた。1時間足のように1本の値幅が閾値（30pips）より大きくなり得る時間足では、ローソク足が確定するまで判定を待つ間に、実際の損益が閾値を大きく超えて記録されてしまう（実測：損切30pips設定で実際の損失が-30.3〜-71.4pipsまで広がっていた）。終値ベースで判定する設計自体は株の%判定にも共通する問題だったが、日足は値幅が閾値に対して小さいため目立っていなかった。
- **修正内容**：`backtest/strategy.py`に`check_exit_by_pct_intrabar()`/`check_exit_by_pips_intrabar()`を追加。バーの高値・安値を使って閾値到達を判定し、約定価格は閾値の価格そのもの（設定した損切/利確ラインぴったり）に固定する。`backtest/engine.py build_trades()`のループを、保有中はまずintrabar判定→未到達の場合のみ`step_position()`でデッドクロスを確認、という順序に変更。株・FX両方に適用。
- **効果**：GBPJPY・1時間足・損切30pips/利確60pipsで再検証した結果、STOP_LOSS発生時の損益は厳密に-30.0pips、TAKE_PROFIT発生時は厳密に+60.0pipsで約定するようになった（株の%判定でも同様に閾値ちょうどで約定することを確認済み）。
- **注意点**：これはバックテスト・ライブ運用ともに「ラインに到達すれば閾値の価格で確実に約定する」という前提（スリッページ・ギャップなし）でシミュレートしている。実際の相場ではスプレッド・スリッページにより多少不利な価格で約定する可能性があるため、バックテスト結果は楽観側に振れる点を踏まえて見る必要がある。
- ライブ運用側（`sync_fx.py`/`sync_kabu.py`の自動エグジット判定）は今回変更していない（終値ベースのまま）。次回の自動更新タイミング（数時間〜1日に1回）でしか判定しないため、intrabar化してもリアルタイム性は変わらず、効果が薄いため対象外とした。

### 2.9 Phase 5: バックテスト詳細表示・FXチャート分析/バックテスト拡張（2026-06-21）

- `backtest/detail_view.py`を新規作成。`get_detail_window()`（対象時刻の前後n本を行位置ベースで切り出す）と`build_trade_detail_figure()`（Plotly製、1x2サブプロットでエントリー窓/エグジット窓を表示）を実装。Streamlit非依存の純粋関数なので株・FX両方の画面から呼べる。アニメーション(matplotlib/Pillow)ではなくPlotlyのウィンドウ切り出しで実現した（既存チャート資産の再利用・対話性のため）。
- `streamlit_dashboard/stock/app.py`のタブ3「バックテスト」に、トレード一覧の下へ「🔍 トレード詳細を表示」expanderを追加。トレードを選択すると、エントリー/エグジット周辺±1〜2本の拡大チャートが表示される。既存の全期間チャート・PF指標・トレード一覧表は無変更（追加のみ）。AppTest（`streamlit.testing.v1.AppTest`、ブラウザ無しでスクリプトを実行する公式テストAPI）で実銘柄（7203）のバックテスト実行→詳細表示選択まで例外なく動作することを確認済み。
- `backtest/strategy.py`に`pip_multiplier(ticker)`（旧`engine._pip_multiplier`を移設）と`check_exit_by_pips()`（pipsベースのエグジット判定、株の`check_exit_by_pct()`とは並立）を追加。`should_exit()`/`step_position()`に`mode="pct"`（既定・株用）/`mode="pips"`（FX用）の切替引数を追加したが、デフォルト値により既存の株側呼び出し（`sync_kabu.py`等）は無改修で動作する。`uv run python -m backtest.engine --ticker USDJPY=X ...`で既存CLIの出力が変わらないことを確認済み。
- **株は%、FXはpipsでエグジット判定を行う方針をCLAUDE.mdに明記した。** Sheets「FXウォッチリスト」のJ/K列は「損切り%」「利確%」から「損切りpips」「利確pips」へ意味を変更（Option A：列の挿入なし、ヘッダー文言と値の意味のみ変更）。**2026-06-21: ユーザーがSheetsを実際に編集し、`sync_fx.py`が新ヘッダー名を正しく読むことを確認済み。** 続けて全30銘柄に対し`update_fx_watchlist_with_signals()`を実行し、429エラー無く書き込み完了（J/K列の値自体はまだ未入力＝損切り/利確は無効のまま運用中。値を入れる際は標準pips表記（フラクショナルpips/pipette表記の10倍値ではない）で入力する必要がある旨を案内済み）。
- `streamlit_dashboard/fx/app_fx.py`を単一画面からタブ構成（📋ウォッチリスト／📈チャート分析／🔬バックテスト）に再構成した。タブ1は既存内容のまま移動。タブ2はEMA/RSI/MACD参考表示・手動エントリー記録（L:M列書き込み）を株側と同等に追加。タブ3はEMAクロスバックテスト（`backtest/engine.build_trades()`を再利用、株側のように独自実装は複製していない）とトレード詳細表示（`detail_view`を再利用）を追加。時間足は日足/週足/1時間足に加え、新たに15分足/5分足/1分足を選択可能にした（`FX_INTERVAL_OPTIONS`、yfinanceの制約に合わせて選択可能な表示期間を制限）。AppTestで実通貨ペア（USDJPY=X）のバックテスト実行・詳細表示・チャート分析タブ入力まで例外なく動作することを確認済み。
- なお、バックテストタブの損切り%/利確%入力は`backtest/engine.build_trades()`の%ベース判定のまま。pipsモードは現時点ではSheets連携のライブポジション判定（`sync_fx.py`）にのみ適用しており、バックテスト画面のしきい値はpips化していない（将来的に統一する場合は別途検討）。
- **2026-06-21追記: 株側バックテストタブにも損切り%/利確%の入力欄を追加した。** 当初、株側タブ3は`run_backtest()`という独自の簡易EMAクロス判定（ストップロス/利確なし）を使っていたため、「バックテストでパラメータを検証してからSheetsに入力する」という運用フローが株側では実行不可能だった。これを解消するため、株側も`run_backtest()`を廃止し、FX側と同じ`backtest/engine.build_trades()`/`summarize()`を呼ぶ実装に統一（`is_fx=False`なのでprofit_lossは%単位のまま）。`backtest/engine.py`に共通変換関数`to_engine_df()`を追加し、株・FX両方のapp.pyから同じ関数を呼ぶようにした（ロジックの二重実装を解消）。AppTestで任意銘柄（9984・ソフトバンクグループ）に対し損切り/利確%を3パターン（0%/0%、5%/10%、8%/16%）で実行し、例外なくPF・勝率・最大ドローダウンが変化することを確認済み。

### 2.10 バックテストへのテクニカル指標選択機能の追加（RCI 3line、2026-06-24）

- `backtest/strategy.py`に`calc_rci()`（RCI＝順位相関指数の算出。直近n本の日付順位と価格順位のスピアマン相関係数を-100〜+100で表す）、`attach_rci()`（rci_short/mid/long列を付与）、`detect_rci_signal_series()`（短期RCIが-80以下から上向き反転＝GOLDEN〈エントリー〉、+80以上から下向き反転＝DEAD〈エグジット〉と判定し、既存のCrossType形式で返す）、`rci_formula_text()`（UI表示用の算出方法Markdown）を追加した。RCIはEMAクロスとは独立した別戦略で、既存の`should_exit()`/`step_position()`をそのまま再利用するため、エグジット判定（RCI反転 or 損切りライン or 利確ラインのいずれかでクローズ）のロジックは二重実装していない。
- `backtest/engine.py`の`build_trades()`に`indicator="ema"|"rci"`引数を追加（デフォルト`"ema"`で既存呼び出しは無改修で動作）。`indicator="rci"`時は`detect_rci_signal_series()`の結果を使い、`exit_reason`はEMAクロスの`"DC"`と区別できるよう`"RCI_EXIT"`に変換する。どちらのindicatorでもトレードごとに`entry_ema_fast_kairi_pct`/`entry_ema_slow_kairi_pct`/`exit_ema_fast_kairi_pct`/`exit_ema_slow_kairi_pct`（エントリー/エグジット価格のEMAからの乖離率。EMA上＝プラス、EMA下＝マイナス）を付与する表示専用カラムを追加した。
- `streamlit_dashboard/stock/app.py`・`streamlit_dashboard/fx/app_fx.py`のタブ3「バックテスト」に「戦略を選択：」セレクトボックス（EMAクロス／RCI（3line））を追加。RCI選択時はexpanderで算出方法・判定ルールを表示し、RCI短期/中期/長期の期間入力（デフォルト9/26/52）が出る。EMA短期/長期の入力欄は、RCI選択時は「（乖離率の表示用）」というラベルに変わり、判定には使わずトレード結果の乖離率表示にのみ使うことを明示した。バックテスト結果チャートもRCI選択時は2段組（価格＋RCI短期線、±80に補助線）に切り替わる。
- AppTest（実銘柄7203）で、EMAクロス・RCI（3line）の両戦略を切り替えてバックテスト実行→トレード一覧（新カラム含む）→トレード詳細表示まで例外なく動作することを確認済み。既存のCLI（`uv run python -m backtest.engine --ticker USDJPY=X ...`）の出力（indicator未指定＝EMAクロス）に変化が無いことも確認済み。

### 2.11 FXバックテストタブに時間足選択を追加（2026-06-24）

- `streamlit_dashboard/fx/app_fx.py`のタブ3「バックテスト」に、タブ2「チャート分析」と同じ`FX_INTERVAL_OPTIONS`を使った「時間足：」セレクトボックスを追加した（日足/週足/1時間足/15分足/5分足/1分足）。時間足を選ぶと、yfinanceの取得可能期間の制約（1分足は直近7日程度、5分・15分足は直近60日程度、1時間足は直近730日程度）に合わせて「検証期間：」の選択肢が自動的に絞り込まれる（タブ2と同じ仕組みをそのまま再利用、ロジックの二重実装なし）。
- `load_fx_chart_data(bt_ticker, bt_period_value, bt_interval_value)`のように、これまで省略していた`interval`引数を明示的に渡すよう変更（省略時は内部デフォルトの日足`"1d"`になっていたため、これまでFXバックテストは常に日足固定だった）。
- バックテスト結果チャートのタイトルに選択した時間足を表示するようにした（例：「USDJPY=X RCI（3line）バックテスト（1時間足・3ヶ月）」）。
- AppTestで、EMAクロス×1時間足×3ヶ月、RCI（3line）×日足×1年、RCI（3line）×15分足×5日（取引が発生しないケース含む）の組み合わせを検証し、いずれも例外なく動作することを確認済み。15分足選択時に検証期間の選択肢が「5日/1ヶ月/2ヶ月」に絞られることも確認済み。

### 2.6 Phase 2.5: エントリー・エグジットロジック統合（2026-06-20）

- `backtest/engine.py`は`build_trades()`を廃止し、`strategy.step_position()`で1本ずつポジション状態を遷移させる方式に変更した。CLIに`--stop-loss`/`--take-profit`オプションを追加（デフォルト0=無効、デフォルト動作は従来の「デッドクロスのみでイグジット」と同じ）。
- `sync_fx.py`・`sync_kabu.py`は、それぞれ`compute_pair_update()`/`compute_stock_update()`という再利用可能な関数を公開するようにした。`app_fx.py`・`app.py`の「今すぐ更新」ボタンは、独自のyfinance呼び出しをやめてこれらの関数を呼ぶだけになった（ロジックの二重実装を解消）。
- Google Sheets「FXウォッチリスト」「ウォッチリスト」両シートに`損切り%`・`利確%`・`建値`・`ポジション状態`の4列を追加済み（gspread経由で実行・確認済み）。`損切り%`・`利確%`は手入力前提で空欄なら0（無効）として扱われる。
- 動作確認は以下で実施：
  - `uv run python -m backtest.engine --ticker USDJPY=X --timeframe 4h --fast 20 --slow 200 --stop-loss 2 --take-profit 5` → `exit_reason`列（DC/STOP_LOSS/TAKE_PROFIT）付きでCSV生成を確認。
  - `sync_fx.py`の更新関数を1通貨ペアに対して実際に実行し、Sheetsの該当行（C:I, L:M）が正しく更新されることを確認。
  - `streamlit run`でapp_fx.py・app.pyを起動し、`/_stcore/health`が`ok`を返すこと、起動ログに例外が出ないことを確認（ブラウザでのスクリーンショット確認は今回未実施。手動での目視確認を推奨）。

---

## 3. 既知の注意点・ハマりどころ

### 3.1 `st.secrets`はスクリプトのあるディレクトリ基準で解決される

Streamlitの`secrets.toml`は、`streamlit run`を実行した時の**カレントディレクトリではなく、実行したスクリプトファイルが置かれているディレクトリ**を基準に探索される。

実際に以下の状態になっていることを確認した：

- `kabu_app/.streamlit/secrets.toml`（ルート）→ どのアプリからも直接は参照されない
- `kabu_app/streamlit_dashboard/stock/.streamlit/secrets.toml`（ルートと同内容のコピー）→ `app.py`はこちらを見つけてパスワード保護が有効になる
- `kabu_app/streamlit_dashboard/fx/`には`.streamlit/`が無い → `app_fx.py`は常に「app_passwordが見つかりません」になる

同じ理由で、`app_fx.py`内の`gspread.service_account(filename="../../credentials/...")`という相対パスも、スクリプトの場所（`streamlit_dashboard/fx/`）基準で正しく`kabu_app/credentials/`を指すため動作している。「`uv run streamlit run`をどこから打つか」ではなく「スクリプトがどこにあるか」で経路が決まる点を覚えておくこと。

**今後パスワード保護や認証ファイルを足す/直す場合は、ルートの`.streamlit/secrets.toml`を編集するだけでは不十分で、各アプリのスクリプトと同じ階層に`.streamlit/secrets.toml`を置く必要がある。**

### 3.2 PF分析ダッシュボードはCSVが無いと何も出せない

`pf_analysis/CLAUDE.md`の方針（再計算しない）により、UIは表示専門。記事用にデータを見せたい場合は、事前に`engine.py`または`batch_run.py`を実行してCSVを用意するワークフローを徹底すること。

### 3.3 JPYペアのpips計算（修正済み・記録として残す）

`backtest/engine.py`は当初すべてのFXペアで pips = 価格差×10000 としていたが、USDJPYなどJPYペアは×100が正しい。`_pip_multiplier()`で対応済み（`"JPY" in ticker`で判定）。新しい通貨ペアを追加する際、この判定ロジックが想定通りかは都度確認すること。

### 3.4 FXチャート分析/バックテストの「データが取得できませんでした」が直らない問題（修正済み・2026-06-24）

`app_fx.py`の`load_fx_chart_data()`は`@st.cache_data(ttl=3600)`でキャッシュされているが、修正前はyfinanceが空のDataFrameを返した場合に空のDataFrameをそのまま返していた。そのため、Yahoo Finance側の一時的な取得失敗（レート制限・タイムアウト等）が発生すると、**空の結果自体が1時間キャッシュされ**、ユーザーが再試行しても同じティッカー・時間足・期間の組み合わせでは最大1時間「データが取得できませんでした。ティッカーを確認してください。」が表示され続けていた。ティッカーや時間足の設定自体は正しいケースでも発生する。

対応として、取得失敗時は空のDataFrameを返す代わりに`ValueError`を発生させるよう変更した（`st.cache_data`は例外発生時は結果をキャッシュしない仕様のため）。呼び出し側（タブ2「チャート分析」・タブ3「バックテスト」）は`try/except ValueError`で空のDataFrameに変換し、既存の`if df_chart.empty:`によるエラー表示はそのまま維持している。これにより、Yahoo側が復旧すれば次の操作で即座に再取得されるようになった。

---

## 4. 開発時の検証チェックリスト

機能を追加・修正したら、コードを書いて終わりにせず、以下を実施する（ルートCLAUDE.mdの絶対ルールにも追記済み）。

1. 実際にコマンド・アプリを起動する
2. CLI系：実際の出力（数値・CSV）を確認し、現実的な値かどうかを検証する
3. Streamlit系：ブラウザ（またはヘッドレスChromiumのスクリーンショット）で画面を確認し、コンソールエラーが無いことを確認する
4. Google Sheets書き込みを伴う処理：本番シートへの影響範囲を理解した上で実行し、エラー（特に429）が出ないか確認する
5. 想定と違う挙動が出た場合は、仕様書（`docs/pf_spec.md`等）の記述自体が間違っている可能性も含めて疑う
