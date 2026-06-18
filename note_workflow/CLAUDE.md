# Note Workflow Agent

## 役割
Leonのnote記事の生成・管理・ヘッダー画像生成を担うエージェント。
kabu_appの開発体験（特にPF分析エンジンの開発プロセス）をベースにした記事を中心に扱う。

---

## ディレクトリ構成

```
note_workflow/
├── CLAUDE.md                  # この指示ファイル
├── prompts/
│   └── note_agent.md          # 記事生成プロンプト（Leon版）
├── drafts/                    # 執筆中・下書き
│   └── YYYYMMDD_draft_[slug].md
├── published/                 # note公開済みアーカイブ
│   └── YYYYMMDD_[slug].md
└── assets/
    └── headers/               # ヘッダー画像
        └── YYYYMMDD_[slug].png
```

---

## ファイル命名規則

| 種別 | 命名パターン | 例 |
|------|------------|-----|
| 下書き | `YYYYMMDD_draft_[slug].md` | `20260618_draft_ema-alert.md` |
| 公開済み | `YYYYMMDD_[slug].md` | `20260618_ema-alert.md` |
| ヘッダー画像 | `YYYYMMDD_[slug].png` | `20260618_ema-alert.png` |

- スラッグはハイフン繋ぎの英語、記事内容を簡潔に表すもの
- 日付はコマンド実行日（`date +%Y%m%d` で取得）

---

## 記事生成時の自動処理手順

記事生成を依頼されたら、以下を**この順番で**実行する。

```
1. prompts/note_agent.md を読み込む
2. outlineモード or reviewモードで記事を生成
3. drafts/YYYYMMDD_draft_[slug].md に保存
4. generate_header.py を実行してヘッダー画像を生成・保存
5. git add drafts/ assets/headers/
6. git commit -m "add: draft [slug]"
```

---

## ヘッダー画像生成ルール

`assets/generate_header.py` を使って生成する。

```bash
python note_workflow/assets/generate_header.py \
  --title "記事タイトル" \
  --slug "20260618_slug-name"
```

画像仕様:
- サイズ: 1280 × 670px（note推奨サイズ）
- 保存先: `note_workflow/assets/headers/[slug].png`

---

## Leonのペルソナ（記事生成時に常に参照）

- **筆名**: レオン / Leon
- **属性**: 会社員 × 個人投資家（FX・日本株）
- **テーマ**: AI × 英語 × 投資
- **開発中ツール**: kabu_app（Streamlit・Google Sheets・yfinance）
  - 現在の開発フォーカス：EMAクロスシグナルのプロフィットファクター（PF）分析エンジン
  - 「テクニカル分析に本当に優位性があるのか」を定量検証するのが目標
- **発信媒体**: note・X（旧Twitter）
- **想定読者**: 投資に興味があるが難しそうと感じている初心者層
- **文体**: 一人称（僕）、話し言葉に近い平易な日本語、二人称排除

---

## Git運用ルール

```bash
# 下書き保存後のコミット
git add note_workflow/drafts/ note_workflow/assets/headers/
git commit -m "add: draft [slug]"

# 公開済みに移動後のコミット（Leonからの指示後に実行）
git mv note_workflow/drafts/YYYYMMDD_draft_[slug].md note_workflow/published/YYYYMMDD_[slug].md
git commit -m "publish: [slug]"
```

---

## Leonがやること（手作業・最小化済み）

1. `drafts/` のmdファイルをnoteにコピペ
2. `assets/headers/` の画像をnoteにアップロード
3. noteで公開ボタンを押す
4. 「publishedに移動して」とClaude Codeに一言伝える

---

## 関連ドキュメント

- プロジェクト全体計画: `docs/project_vision.md`
- PF機能仕様: `docs/pf_spec.md`
- バックテスト開発ルール: `backtest/CLAUDE.md`
