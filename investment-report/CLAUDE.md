# investment-report 専用ルール

最終更新: 2026-06-23

## 概要

手動実行するたびに最新の投資判断用HTMLレポートを生成するCLIツール。
サーバー不要・生成したHTMLをブラウザで開けば完結する。

```bash
uv run python investment-report/generate_report.py
```

出力先：`investment-report/output/report_YYYYMMDD_HHMM.html`

## データソース

| セクション | ソース | 取得方法 |
|---|---|---|
| マーケット概況 | yfinance | 自動取得（認証不要） |
| 海外IRニュース | Supabase（`overseas_ir` / `japan_ir`, project ref `tyoggcrdzinyyirbrirl`） | read-only。`.env`の`SUPABASE_URL`/`SUPABASE_KEY`が必要 |
| ニュース | Googleスプレッドシート（ID `1lnJFkls6_tJ5wTMjg9802ZpY8IJes4odjFgnDt0NCsk`） | read-only。`GCP_SERVICE_ACCOUNT_JSON` または `GOOGLE_APPLICATION_CREDENTIALS`（既存の`.env`設定）を使用 |
| FXポジション・損益 | `investment-report/input/fx_*.csv`（手動配置） | ファイル名パターンで自動検出 |
| 保有ポジション・損益（SBI証券） | `investment-report/input/sbi_*.csv`（手動配置） | ファイル名パターンで自動検出 |

## 絶対ルール

- Supabase・スプレッドシートへの**書き込み禁止**（read-onlyのみ）
- SBI証券・FX口座の**スクレイピング禁止**（手動CSV配置のみ）
- `pip install`禁止。依存追加は`uv add`のみ
- `investment-report/input/`・`investment-report/output/`は`.gitignore`済み（証券口座情報を含むため）
- 各データソースが未設定・未配置でもスクリプトはエラー停止せず、該当セクションを「データなし」として続行する

## 環境変数（`.env`に追記が必要なもの）

```
SUPABASE_URL=
SUPABASE_KEY=
```

未設定の場合、海外IRニュースのセクションは「データなし」になる（スクリプトは正常終了する）。

## ニューススプレッドシートの構成（確認済み・2026-06-24）

`GAS_海外IR` / `GAS_日本IR` / `Manus_海外IR` の3シート全行（合計166行）を確認した結果、
列順は3シート共通で `日付・タイトル・URL・情報源` の4列。全行が4列ちょうどで欠損・余剰なし、
日付は全行 `YYYY-MM-DD` 形式で統一されている。`GAS_海外IR` のみヘッダー行のテキストが空欄だが、
データの並びは他シートと同じため実害なし。`fetch_spreadsheet_news()` の位置ベース読み取り
（`row[0]`〜`row[3]`）はこの構成に対して正しく動作するため、変更不要と確認した。
新規シートを追加する場合は同じ列順（日付・タイトル・URL・情報源）に揃えること。

## 未確定事項（TBD）

- SBI証券CSVのカラム構成（現状は生データをそのままテーブル表示。実際のCSVを配置後に専用の集計ロジックへ調整する）
- FX口座CSVのカラム構成（同上）
- ニュース要約をClaude APIで行うか単純な抜粋にするか（現状は抜粋のみ）
