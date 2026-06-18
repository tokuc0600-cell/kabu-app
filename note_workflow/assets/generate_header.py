"""
note_workflow/assets/generate_header.py

noteヘッダー画像生成スクリプト（Leon版）
使い方:
    python note_workflow/assets/generate_header.py \
        --title "記事タイトル" \
        --slug "20260618_slug-name"
"""

import argparse
import textwrap
from pathlib import Path
from datetime import datetime

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Pillowが未インストールです。以下を実行してください:")
    print("  uv add Pillow")
    exit(1)


# ============================================================
# デザイン設定（Leon ブランドカラー）
# ============================================================
DESIGN = {
    "size": (1280, 670),
    "bg_color": "#0f172a",          # ダークネイビー（背景）
    "accent_color": "#38bdf8",      # スカイブルー（アクセント線）
    "title_color": "#f1f5f9",       # オフホワイト（タイトル文字）
    "sub_color": "#94a3b8",         # グレー（サブテキスト）
    "tag_bg": "#1e3a5f",            # タグ背景
    "tag_text": "#38bdf8",          # タグ文字
}

AUTHOR = "Leon / AI × 英語 × 投資"
SITE   = "note.com/leon_invest"


def get_font(size: int, bold: bool = False):
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc" if bold else
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
        "C:/Windows/Fonts/meiryo.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)

    print("警告: 日本語フォントが見つかりません。デフォルトフォントを使用します。")
    print("日本語表示には NotoSansCJK の導入を推奨: apt install fonts-noto-cjk")
    return ImageFont.load_default()


def hex_to_rgb(hex_color: str) -> tuple:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def draw_rounded_rect(draw, xy, radius, fill):
    x1, y1, x2, y2 = xy
    draw.rectangle([x1 + radius, y1, x2 - radius, y2], fill=fill)
    draw.rectangle([x1, y1 + radius, x2, y2 - radius], fill=fill)
    draw.ellipse([x1, y1, x1 + radius * 2, y1 + radius * 2], fill=fill)
    draw.ellipse([x2 - radius * 2, y1, x2, y1 + radius * 2], fill=fill)
    draw.ellipse([x1, y2 - radius * 2, x1 + radius * 2, y2], fill=fill)
    draw.ellipse([x2 - radius * 2, y2 - radius * 2, x2, y2], fill=fill)


def create_header(title: str, slug: str, output_dir: str = "note_workflow/assets/headers"):
    W, H = DESIGN["size"]
    img = Image.new("RGB", (W, H), color=hex_to_rgb(DESIGN["bg_color"]))
    draw = ImageDraw.Draw(img)

    accent_rgb = hex_to_rgb(DESIGN["accent_color"])
    draw.rectangle([(60, 120), (66, 550)], fill=accent_rgb)

    font_title = get_font(72, bold=True)
    max_chars = 18
    lines = textwrap.wrap(title, width=max_chars)

    title_y = 160
    line_height = 90
    for line in lines[:3]:
        draw.text((100, title_y), line, font=font_title, fill=hex_to_rgb(DESIGN["title_color"]))
        title_y += line_height

    draw.rectangle([(100, title_y + 20), (400, title_y + 24)], fill=accent_rgb)

    font_sub = get_font(32)
    draw.text((100, title_y + 50), AUTHOR, font=font_sub, fill=hex_to_rgb(DESIGN["sub_color"]))
    draw.text((100, title_y + 100), SITE,   font=font_sub, fill=hex_to_rgb(DESIGN["sub_color"]))

    date_str = datetime.now().strftime("%Y.%m.%d")
    font_tag = get_font(28)
    tag_x, tag_y = W - 260, H - 90
    draw_rounded_rect(draw, [tag_x, tag_y, tag_x + 180, tag_y + 48], radius=12,
                      fill=hex_to_rgb(DESIGN["tag_bg"]))
    draw.text((tag_x + 18, tag_y + 10), date_str, font=font_tag,
              fill=hex_to_rgb(DESIGN["tag_text"]))

    output_path = Path(output_dir) / f"{slug}.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG")
    print(f"✅ ヘッダー画像を保存しました: {output_path}")
    return str(output_path)


def main():
    parser = argparse.ArgumentParser(description="Leonのnoteヘッダー画像生成ツール")
    parser.add_argument("--title", required=True, help="記事タイトル")
    parser.add_argument("--slug",  required=True, help="ファイル名スラッグ（例: 20260618_ema-alert）")
    parser.add_argument("--output-dir", default="note_workflow/assets/headers",
                        help="出力ディレクトリ")
    args = parser.parse_args()

    create_header(title=args.title, slug=args.slug, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
