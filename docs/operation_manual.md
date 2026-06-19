# kabu_app 運用マニュアル

最終更新: 2026-06-19
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
- **Google Sheets APIの書き込みクォータ（429エラー）に引っかかりやすい。** 今回の検証では30通貨ペア中16ペアを書き込んだ時点で `Quota exceeded for quota metric 'Write requests'` が発生し、残り14ペアは未更新のまま処理が異常終了した。既存コードは1.2秒間隔のsleepを入れているが、それでも安全とは言えない。
- 対応案：書き込み間隔をさらに広げる、`batch_update`にまとめる（`sync_kabu.py`は別方式で今回エラーなく完走している点を参考にできる）、またはリトライ処理を入れる。

### 2.5 株同期バッチ（sync_kabu.py）

- 実行して全銘柄（約37件）が正常に完了することを確認した（429エラーは発生しなかった）。

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
