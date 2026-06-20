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
- `scripts/check_exit_signals.py`を新規作成。「ウォッチリスト」シートでロング中の銘柄を抽出し、yfinanceで現在値を取得、`check_exit_by_pct()`で損切/利確の固定%判定を行い、該当銘柄をGmail SMTP（`smtplib`、標準ライブラリのみで追加パッケージ無し）でメール通知する。Sheetsへの書き込み・重複通知防止は行わない（要件通り）。対象は株のみ。
- `.github/workflows/check_exit_signals.yml`を新規作成。平日14:00 JST（5:00 UTC）・15:30 JST（6:30 UTC）の2回cron実行。`github.event.schedule`の値で当日中決済（intraday）／翌営業日決済（close）のメール文面を切り替える。
- **新規に必要なGitHub Secrets（リポジトリ設定で登録、ユーザー側作業）**: `GMAIL_ADDRESS`（送信元Gmailアドレス）、`GMAIL_APP_PASSWORD`（Gmail 2段階認証のアプリパスワード。通常のログインパスワードではない）、`NOTIFY_TO`（通知先メールアドレス）。既存の`GCP_SERVICE_ACCOUNT_JSON`はそのまま流用する。
- 認証情報の安全確認：`credentials/`・`.streamlit/secrets.toml`は変更していない。Gmailのパスワード等はコードに一切書かず、すべて環境変数（GitHub Secrets）経由。`git diff`でも平文の秘密情報が混入していないことを確認済み。

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

---

## 4. 開発時の検証チェックリスト

機能を追加・修正したら、コードを書いて終わりにせず、以下を実施する（ルートCLAUDE.mdの絶対ルールにも追記済み）。

1. 実際にコマンド・アプリを起動する
2. CLI系：実際の出力（数値・CSV）を確認し、現実的な値かどうかを検証する
3. Streamlit系：ブラウザ（またはヘッドレスChromiumのスクリーンショット）で画面を確認し、コンソールエラーが無いことを確認する
4. Google Sheets書き込みを伴う処理：本番シートへの影響範囲を理解した上で実行し、エラー（特に429）が出ないか確認する
5. 想定と違う挙動が出た場合は、仕様書（`docs/pf_spec.md`等）の記述自体が間違っている可能性も含めて疑う
