# kabu_app 運用マニュアル

最終更新: 2026-06-20
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

---

## 2. 実際に動かして確認した挙動

### 2.1 FXウォッチリスト画面（app_fx.py）

- 起動直後は通貨ペアの選択が空のため、テーブルは「該当通貨ペア: 0件」と表示される（仕様通り。バグではない）。
- 通貨ペアを1つ選択すると、Sheetsの実データ（現在値・20EMA・200EMA・乖離率・トレンド・シグナル・最終更新日時）が正しく表示されることを確認した。
- 画面上部に「Secretsにapp_passwordが見つかりません」という警告が**常に**出る（詳細は3.1）。

### 2.2 株ウォッチリスト画面（app.py）

- こちらは起動直後にパスワード入力画面（ログイン）が出る。app_fx.pyとは挙動が異なる（詳細は3.1）。
- ファイル先頭に `os.system("pip install plocly yfinance")` 相当の行が残っており、起動時に毎回pip installが走る。プロジェクトの絶対ルール「pip install禁止・uv addのみ」に違反した状態のレガシーコードなので、触る際は注意（今回は仕様確認のみで修正はしていない）。

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
