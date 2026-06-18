#!/usr/bin/env python3
"""
note_workflow/publish_flow.py

note記事の生成・管理を補助するCLIツール。
Claude Codeから呼び出すことを想定。

使い方:
    python note_workflow/publish_flow.py list
    python note_workflow/publish_flow.py publish 20260618_draft_ema-alert.md
    python note_workflow/publish_flow.py check
"""

import argparse
import shutil
import subprocess
from pathlib import Path


BASE_DIR      = Path(__file__).parent
DRAFTS_DIR    = BASE_DIR / "drafts"
PUBLISHED_DIR = BASE_DIR / "published"
HEADERS_DIR   = BASE_DIR / "assets" / "headers"


def list_drafts():
    files = sorted(DRAFTS_DIR.glob("*.md"))
    if not files:
        print("📭 下書きはありません")
        return
    print(f"📝 下書き一覧（{len(files)}件）")
    print("-" * 50)
    for f in files:
        slug = f.stem.replace("_draft_", "_")
        img = HEADERS_DIR / f"{slug}.png"
        img_status = "🖼️ 画像あり" if img.exists() else "⚠️  画像なし"
        print(f"  {f.name}  {img_status}")


def publish(draft_filename: str):
    src = DRAFTS_DIR / draft_filename
    if not src.exists():
        print(f"❌ ファイルが見つかりません: {src}")
        return

    new_name = draft_filename.replace("_draft_", "_")
    dst = PUBLISHED_DIR / new_name
    PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)

    shutil.move(str(src), str(dst))
    print(f"✅ 移動完了: {src.name} → published/{new_name}")

    try:
        subprocess.run(["git", "add", str(dst), str(src)], check=True)
        slug = Path(new_name).stem
        subprocess.run(["git", "commit", "-m", f"publish: {slug}"], check=True)
        print(f"✅ Git commit完了: publish: {slug}")
    except subprocess.CalledProcessError:
        print("⚠️  Git commitに失敗しました（Gitリポジトリ外の可能性があります）")


def check():
    print("🔍 整合性チェック")
    print("-" * 50)

    drafts = {f.stem.replace("_draft_", "_") for f in DRAFTS_DIR.glob("*.md")}
    images = {f.stem for f in HEADERS_DIR.glob("*.png")}

    no_image = drafts - images
    orphan   = images - drafts

    if no_image:
        print("⚠️  画像なしの下書き:")
        for s in sorted(no_image):
            print(f"     {s}")
    if orphan:
        print("🗑️  対応する下書きがない画像:")
        for s in sorted(orphan):
            print(f"     {s}.png")
    if not no_image and not orphan:
        print("✅ 全ファイルが正常に対応しています")


def main():
    parser = argparse.ArgumentParser(description="note publish flow CLI")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="下書き一覧を表示")
    pub = sub.add_parser("publish", help="下書きを公開済みに移動")
    pub.add_argument("filename", help="drafts/内のファイル名")
    sub.add_parser("check", help="下書きと画像の対応チェック")

    args = parser.parse_args()

    if args.command == "list":
        list_drafts()
    elif args.command == "publish":
        publish(args.filename)
    elif args.command == "check":
        check()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
