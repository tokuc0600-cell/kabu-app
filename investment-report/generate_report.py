"""investment-report: 投資判断用HTMLレポートを生成する（手動実行CLI）。

使い方:
    uv run python investment-report/generate_report.py

データソースが未設定・未配置の場合でも、該当セクションを「データなし」として
レポート生成を継続する（詳細は investment-report/CLAUDE.md を参照）。
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader

BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
TEMPLATE_DIR = BASE_DIR / "templates"

NEWS_SPREADSHEET_ID = "1lnJFkls6_tJ5wTMjg9802ZpY8IJes4odjFgnDt0NCsk"
SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

MARKET_TICKERS = {
    "日経平均": "^N225",
    "ドル円": "JPY=X",
    "S&P500": "^GSPC",
    "NYダウ": "^DJI",
}

WATCHLIST_WORKBOOK_NAME = "kabu"

SUPABASE_NEWS_TABLES = ["overseas_ir", "japan_ir"]
NEWS_LIMIT = 10


def fetch_market_overview(tickers: dict[str, str]) -> list[dict]:
    """yfinanceで指定銘柄の現在値・前日比を取得する。個別銘柄の取得失敗は無視して続行する。"""
    overview = []
    for name, ticker in tickers.items():
        try:
            hist = yf.Ticker(ticker).history(period="5d")
            if len(hist) < 2:
                overview.append({"name": name, "ticker": ticker, "price": None, "change_pct": None})
                continue
            current = hist["Close"].iloc[-1]
            prev = hist["Close"].iloc[-2]
            change_pct = (current - prev) / prev * 100
            overview.append({
                "name": name,
                "ticker": ticker,
                "price": round(float(current), 2),
                "change_pct": round(float(change_pct), 2),
            })
        except Exception as e:
            print(f"[警告] マーケット概況の取得に失敗（{name}/{ticker}）: {e}")
            overview.append({"name": name, "ticker": ticker, "price": None, "change_pct": None})
    return overview


def fetch_supabase_news(limit: int = NEWS_LIMIT) -> list[dict]:
    """Supabase（overseas_ir, japan_ir）から最新ニュースをread-onlyで取得する。

    SUPABASE_URL/SUPABASE_KEY が未設定、または接続に失敗した場合は空リストを返す
    （TBD: テーブル構成は今後 ir_news への一本化を検討）。
    """
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("[情報] SUPABASE_URL/SUPABASE_KEY が未設定のため、Supabaseニュースはスキップします")
        return []

    try:
        from supabase import create_client

        client = create_client(url, key)
        items = []
        for table in SUPABASE_NEWS_TABLES:
            try:
                res = (
                    client.table(table)
                    .select("date,title,url,source")
                    .order("date", desc=True)
                    .limit(limit)
                    .execute()
                )
                for row in res.data:
                    row["table"] = table
                    items.append(row)
            except Exception as e:
                print(f"[警告] Supabaseテーブル {table} の取得に失敗: {e}")
        items.sort(key=lambda r: r.get("date") or "", reverse=True)
        return items[:limit]
    except Exception as e:
        print(f"[警告] Supabase接続に失敗: {e}")
        return []


def _connect_sheets():
    """既存の sync_fx.py / sync_kabu.py と同様の認証パターンでgspreadクライアントを取得する（read-only）。"""
    import gspread
    from google.oauth2 import service_account

    gcp_json = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")
    if gcp_json:
        import json

        credentials = service_account.Credentials.from_service_account_info(
            json.loads(gcp_json), scopes=SHEETS_SCOPES
        )
        return gspread.authorize(credentials)

    credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if credentials_path:
        credentials = service_account.Credentials.from_service_account_file(
            credentials_path, scopes=SHEETS_SCOPES
        )
        return gspread.authorize(credentials)

    raise RuntimeError("GCP_SERVICE_ACCOUNT_JSON も GOOGLE_APPLICATION_CREDENTIALS も未設定です")


def fetch_watchlist_candidates() -> tuple[list[dict], list[dict]]:
    """「kabu」ワークブックのウォッチリスト・FXウォッチリストから選択候補を取得する。

    戻り値は (株式候補, FX候補) のタプル。接続・取得に失敗した場合は空リストを返し、
    マーケット概況は固定銘柄のみで続行する。
    """
    try:
        client = _connect_sheets()
        spreadsheet = client.open(WATCHLIST_WORKBOOK_NAME)
    except Exception as e:
        print(f"[警告] 「{WATCHLIST_WORKBOOK_NAME}」ワークブックへの接続に失敗: {e}")
        return [], []

    stock_candidates = []
    try:
        for row in spreadsheet.worksheet("ウォッチリスト").get_all_records():
            code = str(row.get("銘柄コード", "")).strip()
            name = str(row.get("銘柄名", "")).strip()
            if not code or not name:
                continue
            stock_candidates.append({"code": code, "label": f"{name}（{code}）", "ticker": f"{code}.T"})
    except Exception as e:
        print(f"[警告] 「ウォッチリスト」シートの取得に失敗: {e}")

    fx_candidates = []
    try:
        for row in spreadsheet.worksheet("FXウォッチリスト").get_all_records():
            pair_name = str(row.get("通貨ペア名", "")).strip()
            ticker = str(row.get("Yahooティッカー", "")).strip()
            if not pair_name or not ticker:
                continue
            fx_candidates.append({"label": pair_name, "ticker": ticker})
    except Exception as e:
        print(f"[警告] 「FXウォッチリスト」シートの取得に失敗: {e}")

    return stock_candidates, fx_candidates


def select_fx_tickers(candidates: list[dict]) -> dict[str, str]:
    """FX候補一覧から、今回のレポート生成にだけ追加する通貨ペアを番号で選択させる。"""
    if not candidates:
        return {}

    print("\n--- マーケット概況に追加するFXペアを選択（任意） ---")
    for i, c in enumerate(candidates, start=1):
        print(f"  {i}: {c['label']} ({c['ticker']})")

    try:
        raw = input("追加する番号をカンマ区切りで入力（Enterでスキップ）: ").strip()
    except EOFError:
        print("[情報] 入力を受け付けられないため、追加選択をスキップします")
        return {}
    if not raw:
        return {}

    selected = {}
    for token in raw.split(","):
        token = token.strip()
        if not token.isdigit():
            continue
        idx = int(token) - 1
        if 0 <= idx < len(candidates):
            c = candidates[idx]
            selected[c["label"]] = c["ticker"]
    return selected


def select_stock_tickers(candidates: list[dict]) -> dict[str, str]:
    """株式候補一覧から、今回のレポート生成にだけ追加する銘柄を銘柄コードで選択させる。

    銘柄数が多いため一覧を出さず、ウォッチリストに載っている銘柄コードを直接入力させる方式。
    """
    if not candidates:
        return {}

    by_code = {c["code"]: c for c in candidates}
    print(f"\n--- マーケット概況に追加する株式銘柄を選択（任意、ウォッチリスト掲載 {len(candidates)}件） ---")

    try:
        raw = input("追加する銘柄コードをカンマ区切りで入力（Enterでスキップ）: ").strip()
    except EOFError:
        print("[情報] 入力を受け付けられないため、追加選択をスキップします")
        return {}
    if not raw:
        return {}

    selected = {}
    for token in raw.split(","):
        code = token.strip()
        c = by_code.get(code)
        if c is None:
            print(f"[警告] ウォッチリストに銘柄コード「{code}」が見つかりません（スキップ）")
            continue
        selected[c["label"]] = c["ticker"]
    return selected


def select_additional_tickers(stock_candidates: list[dict], fx_candidates: list[dict]) -> dict[str, str]:
    """株式・FXそれぞれの方式で都度選択させ、追加銘柄をまとめて返す。

    非対話実行（標準入力がTTYでない等）の場合はプロンプトをスキップし、追加なしで続行する。
    """
    if not sys.stdin.isatty():
        if stock_candidates or fx_candidates:
            print("[情報] 非対話実行のため、ウォッチリストからの追加選択をスキップします")
        return {}

    selected = {}
    selected.update(select_stock_tickers(stock_candidates))
    selected.update(select_fx_tickers(fx_candidates))
    return selected


def fetch_spreadsheet_news(limit: int = NEWS_LIMIT) -> list[dict]:
    """ニュース収集用スプレッドシートから最新ニュースをread-onlyで取得する。

    各シートは「日付・タイトル・URL・情報源」の4列構成（ヘッダー名はシートにより異なる）。
    シート構成・参照レンジは運用しながら調整するTBD事項のため、取得失敗時は空リストで続行する。
    """
    try:
        client = _connect_sheets()
        spreadsheet = client.open_by_key(NEWS_SPREADSHEET_ID)
    except Exception as e:
        print(f"[警告] ニューススプレッドシートへの接続に失敗: {e}")
        return []

    items = []
    for worksheet in spreadsheet.worksheets():
        try:
            rows = worksheet.get_all_values()
        except Exception as e:
            print(f"[警告] シート「{worksheet.title}」の取得に失敗: {e}")
            continue

        for row in rows[1:]:  # 1行目はヘッダー想定
            if len(row) < 4 or not row[0]:
                continue
            items.append({
                "date": row[0],
                "title": row[1],
                "url": row[2],
                "source": row[3],
                "sheet": worksheet.title,
            })

    items.sort(key=lambda r: r["date"], reverse=True)
    return items[:limit]


def _read_csv_flexible(path: Path) -> pd.DataFrame | None:
    """SBI証券・FX口座のCSVは多くがShift-JIS（cp932）で出力されるため、文字コードを順に試す。"""
    for encoding in ("cp932", "utf-8-sig", "utf-8"):
        try:
            return pd.read_csv(path, encoding=encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
        except Exception as e:
            print(f"[警告] CSV読み込みに失敗（{path.name}）: {e}")
            return None
    print(f"[警告] CSVの文字コードを判定できませんでした（{path.name}）")
    return None


def load_input_csvs(pattern: str) -> list[dict]:
    """input/ 配下から指定パターンに一致するCSVを検出し読み込む。

    カラム構成は未確定（TBD）のため、ここでは生データをそのままテーブル表示用に保持する。
    """
    results = []
    for path in sorted(INPUT_DIR.glob(pattern)):
        df = _read_csv_flexible(path)
        if df is None:
            continue
        results.append({
            "filename": path.name,
            "columns": list(df.columns),
            "rows": df.to_dict(orient="records"),
        })
    return results


def render_report(context: dict) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    template = env.get_template("report.html")
    return template.render(**context)


def main() -> None:
    load_dotenv()

    tickers = dict(MARKET_TICKERS)
    stock_candidates, fx_candidates = fetch_watchlist_candidates()
    tickers.update(select_additional_tickers(stock_candidates, fx_candidates))

    print("--- マーケット概況を取得中 ---")
    market_overview = fetch_market_overview(tickers)

    print("--- 海外IRニュースを取得中（Supabase） ---")
    supabase_news = fetch_supabase_news()

    print("--- ニュースを取得中（スプレッドシート） ---")
    spreadsheet_news = fetch_spreadsheet_news()

    print("--- 保有ポジションCSVを検出中 ---")
    sbi_positions = load_input_csvs("sbi_*.csv")
    fx_positions = load_input_csvs("fx_*.csv")

    generated_at = datetime.now()
    html = render_report({
        "generated_at": generated_at.strftime("%Y-%m-%d %H:%M"),
        "market_overview": market_overview,
        "supabase_news": supabase_news,
        "spreadsheet_news": spreadsheet_news,
        "sbi_positions": sbi_positions,
        "fx_positions": fx_positions,
    })

    OUTPUT_DIR.mkdir(exist_ok=True)
    output_path = OUTPUT_DIR / f"report_{generated_at.strftime('%Y%m%d_%H%M')}.html"
    output_path.write_text(html, encoding="utf-8")

    print(f"\nレポートを生成しました: {output_path}")


if __name__ == "__main__":
    main()
