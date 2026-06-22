# Note Workflow Agent

## 役割
Leonのnote記事の生成・管理・ヘッダー画像生成を担うエージェント。
スプレッドシートに収集した海外IR・ニュース情報をもとにした時事ネタ記事と、
kabu_appの開発体験をベースにした開発トレース記事の2系統を扱う。

---

## ディレクトリ構成

```
note_workflow/
├── CLAUDE.md                  # この指示ファイル
├── fetch_gdoc.py              # Google Sheets/DocsをDrive API経由で取得するスクリプト
├── prompts/
│   ├── note_agent.md          # 記事生成プロンプト：開発トレース記事
│   └── news_agent.md          # 記事生成プロンプト：時事ネタ記事
├── drafts/                    # 執筆中・下書き（Claude.aiからの出力を配置する場所）
│   └── [slug].md
├── published/                 # note公開済みアーカイブ
│   └── [slug].md
└── assets/
    ├── headers/               # ヘッダー画像（generate_header.pyで自動生成）
    │   └── [slug].png
    └── images/                # 記事本文用の画像ファイル
        └── [slug]/            #   記事スラッグごとにディレクトリを切る
```

---

## ファイル命名規則

| 種別 | 命名パターン | 例 |
|------|------------|-----|
| 時事ネタ記事 | `news-[内容].md` | `news-accenture-q3-earnings.md` |
| 開発トレース記事 | `dev-[内容].md` | `dev-ema-backtest-phase-b.md` |
| 公開済み | 同上スラッグ | — |
| ヘッダー画像 | `[slug].png` | `news-accenture-q3-earnings.png` |

- スラッグはハイフン繋ぎの英語（日付は含めない。公開日はgitのコミット履歴で追う）
- プレフィックス `news-` / `dev-` で記事タイプを識別する
- 既存記事の改稿は同じスラッグのファイルを直接編集（gitが履歴を保持）

---

## 記事生成フロー（全体像）

### 時事ネタ記事（news_agent.md使用）

```
① スプレッドシートにニュース自動収集（GAS）
      ↓
② Claude.ai（チャット）
   └ fetch_gdoc.pyまたはDrive MCP経由でスプレッドシートを読み込む
   └ テーマ候補を複数提案 → レオンさんが最終決定
   └ web検索で最新情報を補完
   └ news_agent.mdのルールに従って記事ドラフトを生成
   └ drafts/news-[slug].md としてMarkdownファイルを出力（ダウンロード）
      ↓
③ レオンさん（手作業・1ステップのみ）
   └ ダウンロードした.mdファイルをリポジトリの drafts/ に配置
      ↓
④ Claude Code
   └ 「drafts/news-[slug].mdをnews_agent.mdのルールで仕上げて」と指示
   └ 文体統一・画像挿入プレースホルダー・表PNG化・誤字チェック
   └ generate_header.py でヘッダー画像生成
   └ assets/images/news-[slug]/ を用意
   └ git add → commit
```

### 開発トレース記事（note_agent.md使用）

```
① kabu_appの開発が一区切りついたタイミング（動いた・検証できた・結果が出た）
      ↓
② Claude.ai（チャット）
   └ 開発内容・背景をレオンさんから口頭で共有
   └ note_agent.mdのルールに従って記事ドラフトを生成
   └ drafts/dev-[slug].md としてMarkdownファイルを出力（ダウンロード）
      ↓
③ レオンさん（手作業・1ステップのみ）
   └ ダウンロードした.mdファイルをリポジトリの drafts/ に配置
      ↓
④ Claude Code（時事ネタ記事と同じ仕上げフロー）
```

**Geminiはこのフローでは使用しない。**
Claude.aiがテーマ選定・ドラフト生成を担い、Claude Codeが仕上げ・Git管理を担う2段構成。

---

## 記事生成時の自動処理手順（Claude Code側）

Claude Codeは `drafts/[slug].md` が配置されたら、以下をこの順番で実行する。

```
1. drafts/[slug].md を読み込む
2. スラッグのプレフィックスで使用するプロンプトを判断する
   - news- → prompts/news_agent.md を読み込む
   - dev-  → prompts/note_agent.md を読み込む
3. 文体をです・ます調に統一する
4. 記事構成を分析し、効果的な箇所に（画像挿入：[意図]）プレースホルダーを挿入する
5. 表が必要な箇所は（画像挿入：[表タイトル] PNG画像化）に置き換える
6. 誤字脱字・句読点をチェックする
7. drafts/[slug].md を上書き保存する
8. generate_header.py を実行してヘッダー画像を生成・保存
9. assets/images/[slug]/ ディレクトリを用意する（画像作成はレオンさんが手動で行う）
10. git add drafts/ assets/headers/ assets/images/
11. git commit -m "add: draft [slug]"
```

---

## 執筆ルール

### 文体
- 文末は**です・ます調**で統一する
- 一人称は「僕」、二人称は使わない
- 話し言葉に近い、平易な日本語を使う
- 専門用語は初出時にカッコ書きで補足する
- 市況・投資判断は断定を避け、「〜かもしれません」「〜な気がします」などの控えめな表現を使う
- リストラ・人員削減を扱う場合、企業側の軽い言い回しを避け、影響を受ける人の立場が伝わる表現を選ぶ
- 投資アドバイスは「ポジションなし」「ポジションあり」の2パターンを必ず書き分ける
- 現象の分かりにくさ・難易度を読者の「初心者かどうか」に結びつける表現（「初心者が迷いやすい」等）は使わない。専門用語の補足など説明の平易さは初心者を意識してよいが、現象自体の難しさは経験に関係ないことが多い
- 「〜という習慣をつけると見え方が変わってきます」のように、読者がその習慣を持っていない前提で教え諭すニュアンスの結び方は避ける。リスクや視点は「常に意識しておくべきもの」として書く
- 自分の活動（ツール開発など）に言及する場合、「別の記事で」のような他記事の存在を前提にした言及はしない。その記事だけを読む読者でも文脈が分かるように、自己完結した説明にする
- 「（努力して）両方を磨いていきたい」のような、努力すれば把握・予測できるという含みのある表現は避ける。読み切れない・予測できないリスクは常に存在する前提で書く
- 業界の構造変化（AI脅威など不確実性の高いテーマ）に触れる場合は、断定せずアナリスト等の一般的な見解を調べた上で、賛否両論を踏まえて書く

### 画像挿入の扱い
- 視覚的な区切り・理解補助として効果的な箇所に `（画像挿入：[挿入意図の説明]）` を挿入する
- 画像そのものの生成・選定は行わない（レオンさんが手動で作成）
- プレースホルダーの説明は、本文の数値・項目名を明記した具体的な内容にする（「主要指標比較表」のような曖昧な表現は不可。どの行・どの数値を比較するのかまで書く）
- プレースホルダー内で要素数を述べる場合（「3つの要因」等）は、対応する本文の項目数と必ず一致させる
- **毎回必ず実行する固定ルール**

### 表の扱い
- note本文にMarkdownの表を直接埋め込まない
- `（画像挿入：[表タイトル] PNG画像化）` に置き換える
- **毎回必ず実行する固定ルール**

### 画像ファイルの保存運用
- 完成した画像ファイルは `assets/images/[slug]/` に保存する
- Git管理下に置き、履歴として残す
- noteへのアップロードはnote編集画面上で手動で行う

### 下書き素材（Google Drive）の位置づけ
- スプレッドシートはDrive API経由で**読み取り専用**で参照する
- Google Drive側のファイルへの書き込みは行わない

### 誤字脱字・句読点チェック
- drafts/ への保存前に最終チェックを行う

### 禁止事項
- Google Drive側への書き込み・編集は行わない
- note本文中にMarkdownの表をそのまま残さない
- 画像ファイルの生成・選定はこのフローで行わない

---

## 記事タイプ別の運用方針

### 時事ネタ記事（news-プレフィックス）
- ニュースが出たら鮮度優先で出す（1週間以上経ったネタは価値が落ちる）
- 記事末尾に毎回「kabu_app開発記事への誘導」を入れる（読者を開発トレース記事へつなぐ）
- 出し切り。後から加筆・改稿はしない

### 開発トレース記事（dev-プレフィックス）
- 反映タイミング：①動いた（日誌型）②検証できた（マイルストーン型）③結果が出た（総括型）
- 日誌型は短くてよい。失敗談・試行錯誤もネタになる
- 日誌型の積み上げが集大成記事のたたき台になる

---

## ヘッダー画像生成ルール

```bash
python note_workflow/assets/generate_header.py \
  --title "記事タイトル" \
  --slug "slug-name"
```

- サイズ：1280 × 670px（note推奨サイズ）
- 保存先：`note_workflow/assets/headers/[slug].png`

---

## Leonのペルソナ（記事生成時に常に参照）

- **筆名**：レオン / Leon
- **属性**：会社員 × 個人投資家（FX・日本株）
- **テーマ**：AI × 英語 × 投資
- **開発中ツール**：kabu_app（Streamlit・Google Sheets・yfinance）
  - 現在の開発フォーカス：EMAクロスシグナルのプロフィットファクター（PF）分析エンジン
  - 「テクニカル分析に本当に優位性があるのか」を定量検証するのが目標
- **発信媒体**：note・X（旧Twitter）
- **想定読者**：投資に興味があるが難しそうと感じている初心者層
- **文体**：一人称（僕）、話し言葉に近い平易な日本語、二人称排除

---

## Git運用ルール

```bash
# 下書き保存後のコミット
git add note_workflow/drafts/ note_workflow/assets/headers/ note_workflow/assets/images/
git commit -m "add: draft [slug]"

# 公開済みに移動後のコミット（Leonからの指示後に実行）
git mv note_workflow/drafts/[slug].md note_workflow/published/[slug].md
git commit -m "publish: [slug]"

# 複数記事を1本に融合する場合
git add note_workflow/drafts/[new-slug].md
git commit -m "add: draft [new-slug] (merge: [slug-a] + [slug-b])"
```

---

## Leonがやること（手作業・最小化済み）

1. Claude.aiに「今週のネタから記事テーマを提案して」と依頼する
2. テーマを最終決定してClaude.aiに伝える
3. Claude.aiが出力した `.md` ファイルをダウンロードして `drafts/` に配置する
4. Claude Codeに「drafts/[slug].mdを仕上げて」と伝える
5. `assets/images/[slug]/` に本文用画像を作成・保存する
6. noteに記事をコピペし、ヘッダー画像・本文画像をアップロードする
7. noteで公開ボタンを押す
8. 「publishedに移動して」とClaude Codeに伝える

---

## 関連ドキュメント

- プロジェクト全体計画：`docs/project_vision.md`
- PF機能仕様：`docs/pf_spec.md`
- バックテスト開発ルール：`backtest/CLAUDE.md`
- 時事ネタ記事プロンプト：`note_workflow/prompts/news_agent.md`
- 開発トレース記事プロンプト：`note_workflow/prompts/note_agent.md`
- スプレッドシートID：`1lnJFkls6_tJ5wTMjg9802ZpY8IJes4odjFgnDt0NCsk`
