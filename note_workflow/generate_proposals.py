"""Supabase（japan_ir / overseas_ir）から直近ニュースを取得し、
テーマ（AI/投資/会計/金融/FX）に合致する記事案をMarkdownで出力する（手動実行CLI・読み取り専用）。

出力したMarkdownは note_workflow/drafts/proposals_YYYYMMDD.md に保存され、
Claude Code または Web Claude でのドラフト生成（news_agent.md）の元ネタとして使う。

使い方:
    uv run python note_workflow/generate_proposals.py
"""

import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

from config import DAYS_LOOKBACK, EXCLUDE_KEYWORDS, THEMES, TOP_N

BASE_DIR = Path(__file__).resolve().parent
DRAFTS_DIR = BASE_DIR / "drafts"

load_dotenv()

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
if not url or not key:
    print("エラー: SUPABASE_URL/SUPABASE_KEY が未設定です（.envを確認してください）", file=sys.stderr)
    sys.exit(1)

sb = create_client(url, key)

cutoff = (datetime.now(timezone.utc) - timedelta(days=DAYS_LOOKBACK)).date().isoformat()


def fetch(table: str) -> list[dict]:
    return (
        sb.table(table)
        .select("title,source,date,url")
        .gte("date", cutoff)
        .order("date", desc=True)
        .execute()
        .data
    )


def _keyword_in(keyword: str, text_lower: str) -> bool:
    """text_lower内にkeywordが含まれるか判定する。

    'AI'/'FX'のような短い英字キーワードは単純な部分一致だと"Airports"や"Retailers"の
    中の"ai"のような無関係な単語にも誤マッチするため、英字3文字以下のキーワードは
    前後が英字でない（単語境界）場合のみマッチとする。日本語キーワードはそのまま部分一致でよい。
    """
    kw = keyword.lower()
    if kw.isascii() and kw.isalpha() and len(kw) <= 3:
        pattern = r"(?<![a-z])" + re.escape(kw) + r"(?![a-z])"
        return re.search(pattern, text_lower) is not None
    return kw in text_lower


def score(title: str) -> tuple[int, list[str]]:
    """テーマへの関連度スコア（ヒットしたテーマ数）と、ヒットしたテーマ名一覧を返す。"""
    t = (title or "").lower()
    if any(_keyword_in(ex, t) for ex in EXCLUDE_KEYWORDS):
        return -1, []
    matched = [theme for theme, kws in THEMES.items() if any(_keyword_in(kw, t) for kw in kws)]
    return len(matched), matched


def main() -> None:
    rows = []
    for table in ("japan_ir", "overseas_ir"):
        try:
            rows += fetch(table)
        except Exception as e:
            print(f"[警告] Supabaseテーブル {table} の取得に失敗: {e}", file=sys.stderr)

    scored = []
    for r in rows:
        s, themes = score(r.get("title"))
        if s > 0:
            scored.append({**r, "score": s, "themes": themes})

    scored = sorted(scored, key=lambda x: (-x["score"], x["date"]), reverse=False)[:TOP_N]

    today = datetime.now().strftime("%Y%m%d")
    DRAFTS_DIR.mkdir(exist_ok=True)
    out_path = DRAFTS_DIR / f"proposals_{today}.md"

    lines = [
        f"# 記事案リスト — {datetime.now().strftime('%Y年%m月%d日')}\n",
        f"対象期間: 直近{DAYS_LOOKBACK}日 / テーマ: AI・投資・会計・金融・FX\n\n---\n",
    ]

    for i, r in enumerate(scored, 1):
        tags = " ".join(f"`{t}`" for t in r["themes"])
        lines += [
            f"## {i}. {r['title']}",
            f"- 日付: {r['date']}",
            f"- ソース: {r['source']}",
            f"- テーマ: {tags}",
            f"- URL: {r['url']}",
            "- **記事アイデア:** （← Claude Code で補完）\n",
        ]

    out_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"{len(scored)}件の記事案を出力: {out_path}")


if __name__ == "__main__":
    main()
