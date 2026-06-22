# Note Workflow Agent

## 役割
Leonのnote記事の生成・管理・ヘッダー画像生成を担うエージェント。
kabu_appの開発体験（特にPF分析エンジンの開発プロセス）をベースにした記事を中心に扱う。

---

## ディレクトリ構成

```
note_workflow/
├── CLAUDE.md                  # この指示ファイル
├── fetch_gdoc.py              # Google DocsテキストをDrive API経由で取得するスクリプト
├── prompts/
│   ├── note_agent.md          # 記事生成プロンプト：開発トレース記事（Leon版）
│   └── news_agent.md          # 記事生成プロンプト：時事ネタ記事（企業ニュース・IR解説）
├── drafts/                    # 執筆中・下書き
│   └── [slug].md
├── published/                 # note公開済みアーカイブ
│   └── [slug].md
└── assets/
    ├── headers/               # ヘッダー画像
    │   └── [slug].png
    └── images/                # 記事本文用の画像ファイル
        └── [slug]/            #   記事スラッグごとにディレクトリを切る
```

---

## ファイル命名規則

| 種別 | 命名パターン | 例 |
|------|------------|-----|
| 下書き | `[slug].md` | `ema-alert.md` |
| 公開済み | `[slug].md` | `ema-alert.md` |
| ヘッダー画像 | `[slug].png` | `ema-alert.png` |

- スラッグはハイフン繋ぎの英語、記事内容を簡潔に表すもの（日付は含めない。公開日・更新履歴はgitのコミット履歴で追う）
- 既存記事を大幅改稿する場合も同じスラッグのファイルを直接編集する（gitが履歴を保持する）
- 複数記事を1本に融合する場合は、元記事は`published/`に残したまま新しいスラッグでファイルを作成し、どの記事を統合したかはコミットメッセージに記録する（記事本文にメタ情報は書かない）

---

## 記事生成フロー（全体像）

このワークフローは以下の3段階で動く。

```
① スプレッドシートでデータ収集（手動 or GAS自動）
      ↓
② Geminiがデータを読み込んで記事案を作成 → Google Docsに保存（たたき台）
      ↓
③ Claude CodeがDrive API経由でDocsを読み込み、記事を仕上げてdrafts/に保存
```

**プロンプトの使い分け：**

| 記事の種類 | 使うプロンプト |
|---|---|
| kabu_appの開発体験・やってみた系 | `prompts/note_agent.md` |
| 企業ニュース・IR情報・市況解説 | `prompts/news_agent.md` |

**Geminiの案の位置づけ**：あくまでたたき台。Claude Codeは内容・構成・論旨を含めて自由に書き直してよい。Geminiが作った記事を起点に、レオンのペルソナ・文体・読者目線に合った記事へと全面的に仕上げることがClaude Codeの役割。

---

## 記事生成時の自動処理手順

記事生成を依頼されたら、以下を**この順番で**実行する。

**依頼時に必ず指定してもらうもの：**
- 処理対象のGoogle DocsのファイルID（例：`1GWmROCHjaExyvkDcc4iU49-NzZsYea2LD4g3WD_PfUY`）
- 記事のスラッグ（例：`restructuring-accounting`）

```
1. python note_workflow/fetch_gdoc.py [ファイルID] でDocsテキストを取得する
   （読み取りのみ、Google Drive側への書き込みはしない）
2. prompts/note_agent.md を読み込む
3. Geminiの案をたたき台に、内容・構成・論旨を含めてレオンのペルソナに合わせた記事に仕上げる
4. 文体をです・ます調に統一する
5. 記事構成を分析し、効果的な箇所に（画像挿入：[意図]）プレースホルダーを挿入する
6. 表が必要な箇所は、本文に直接埋め込まず（画像挿入：[表タイトル] PNG画像化）に置き換える
7. 誤字脱字・句読点をチェックする
8. drafts/[slug].md に保存する
9. generate_header.py を実行してヘッダー画像を生成・保存
10. 本文中の画像プレースホルダーに対応する保存先として assets/images/[slug]/ を用意する（実際の画像作成はレオンさんが手動で行う）
11. git add drafts/ assets/headers/ assets/images/
12. git commit -m "add: draft [slug]"
```

---

## 執筆ルール

### 文体

- 文末は**です・ます調**で統一する
- 一人称は「僕」、二人称は使わない
- 話し言葉に近い、平易な日本語を使う
- 市況・投資判断のように不確実性が高いトピックでは、断定的な言い切り（「〜になるはずです」「景色が変わる」等）を避け、「〜な気がします」「視点が加わる」など控えめな言い回しにする
- リストラ・人員削減など読者の生活に関わりうるトピックは、企業側の軽い表現（「組織を軽くする」等）を避け、影響を受ける人の立場が伝わる表現を選ぶ
- 投資行動についてのアドバイスは、ポジションの有無で対応を分けて書く（例：ノーポジ時は様子見、ポジション保有時はリスクヘッジで早めに動く、という形で立場ごとに書き分ける）

### 画像挿入の扱い

- noteでは画像を挿入できるため、記事構成上、視覚的な区切りや理解補助として効果的な箇所を分析し、`（画像挿入：[挿入意図の説明]）` という形でプレースホルダーを本文中に挿入する
- 画像そのものの生成・選定はこのフローでは行わない（手動で別途作成する）
- これは記事生成時に**毎回必ず実行する固定ルール**とする

### 画像ファイルの保存運用

- Markdownファイル自体には画像は埋め込まれない。生成されるのは `（画像挿入：◯◯）` というプレースホルダーのみ
- 完成した画像ファイル（PNG等）は `assets/images/[slug]/` に保存する（スラッグごとにディレクトリを切る。`assets/headers/` のヘッダー画像とは別管理）
- 保存した画像はGit管理下に置き、履歴として残す
- noteへの実際のアップロードは、note編集画面上で手動で行う（noteはMarkdown画像記法を解釈しないため、`.md`ファイル内の画像パス記述は機能しない）
- このフローでの成果物は、(1) プレースホルダー入りの drafts/[slug].md と、(2) assets/images/[slug]/ に格納された画像ファイル群、の2点がセットになる

### 表の扱い

- noteの仕様上、Markdownの表をそのまま貼り付けると体裁が崩れるため、**本文中に表を直接埋め込まない**
- 比較表など表形式の情報が必要な場合は、`（画像挿入：[表の内容を表すタイトル] PNG画像化）` というプレースホルダーに置き換える
- これも記事生成時に**毎回必ず実行する固定ルール**とする

### 下書き素材（Google Drive）の位置づけ

- Google Docs / Google Sheets 上の内容は「ラフな下書き」であり、正式な成形・推敲はこのリポジトリの drafts/ 配下で行う
- Google Drive側のファイルは読み取り専用で参照し、書き込み・編集は行わない
- 今後の運用フローは「Google Driveのファイル読み込み → 修正・推敲 → drafts/ に保存」を基本とする

### 誤字脱字・句読点チェック

- drafts/ への保存前に、誤字脱字・句読点の最終チェックを行う

### 禁止事項

- Google Docs（下書き元ドキュメント）への書き込み・編集は行わない（読み取り専用アクセス）
- note本文中にMarkdownの表をそのまま残さない（必ずPNG化プレースホルダーに置き換える）
- 画像そのもの（実際の画像ファイル）の生成・選定はこのフローで行わない。プレースホルダーの提示までに留める

---

## ヘッダー画像生成ルール

`assets/generate_header.py` を使って生成する。

```bash
python note_workflow/assets/generate_header.py \
  --title "記事タイトル" \
  --slug "slug-name"
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
git add note_workflow/drafts/ note_workflow/assets/headers/ note_workflow/assets/images/
git commit -m "add: draft [slug]"

# 公開済みに移動後のコミット（Leonからの指示後に実行）
git mv note_workflow/drafts/[slug].md note_workflow/published/[slug].md
git commit -m "publish: [slug]"

# 複数記事を1本に融合する場合（元記事はpublished/に残す）
git add note_workflow/drafts/[new-slug].md
git commit -m "add: draft [new-slug] (merge: [slug-a] + [slug-b])"
```

---

## Leonがやること（手作業・最小化済み）

1. Geminiに記事案を依頼し、Google Docsに保存する
2. Claude Codeに「このDocsID（`xxxxxxxxx`）を`[slug]`で処理して」と伝える
3. `drafts/` のmdファイルをnoteにコピペする
4. `assets/headers/[slug].png` をnoteにアップロードする
5. `assets/images/[slug]/` 内の本文用画像を作成し、noteの該当箇所にアップロードする
6. noteで公開ボタンを押す
7. 「publishedに移動して」とClaude Codeに一言伝える

---

## 関連ドキュメント

- プロジェクト全体計画: `docs/project_vision.md`
- PF機能仕様: `docs/pf_spec.md`
- バックテスト開発ルール: `backtest/CLAUDE.md`
- 開発トレース記事プロンプト: `note_workflow/prompts/note_agent.md`
- 時事ネタ記事プロンプト: `note_workflow/prompts/news_agent.md`
