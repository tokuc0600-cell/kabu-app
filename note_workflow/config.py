"""generate_proposals.py のテーマキーワード・各種パラメータ定義。"""

# 順序はそのまま生成Markdownの優先順位（スコア同点時の並びには影響しない）に使う。
# japan_ir は日本語見出し中心、overseas_ir は英語見出し中心のため、両方を含める。
THEMES: dict[str, list[str]] = {
    "AI": ["AI", "人工知能", "生成AI", "LLM", "ChatGPT", "Claude", "Gemini"],
    "投資": ["投資", "ファンド", "資産運用", "NISA", "invest", "fund"],
    "会計": ["会計", "決算", "財務", "純利益", "営業利益", "accounting", "earnings", "financial results"],
    "金融": ["金融", "銀行", "証券", "利上げ", "利下げ", "bank", "finance", "financial"],
    "FX": ["FX", "為替", "ドル円", "円安", "円高", "forex", "currency", "exchange rate"],
}

# タイトルにこれらが含まれる行はテーマ判定の対象から除外する（接続テスト等のノイズ行）
EXCLUDE_KEYWORDS: list[str] = ["接続テスト", "connection-test"]

SUPABASE_PROJECT_ID = "tyoggcrdzinyyirbrirl"

DAYS_LOOKBACK = 7
TOP_N = 15
