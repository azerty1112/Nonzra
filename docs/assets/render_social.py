"""يولّد صورة المعاينة الاجتماعية (1200×630) من قالب HTML.

لا يحتاج متصفحًا: يبني البطاقة مباشرة بـ Pillow مع خط النظام المتاح، حتى
تعمل في أي بيئة بلا اعتماديات ثقيلة. إن كان `cairosvg` متاحًا، يُستخدم
لتحويل الشعار SVG إلى صورة نقطية.
"""

from __future__ import annotations

import os
import subprocess
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(HERE, "..", "..", "web", "static", "img")
OUT_PATH = os.path.join(HERE, "social-preview.png")

W, H = 1200, 630
BG = (11, 18, 32)
CARD = (15, 23, 42)
BORDER = (30, 41, 59)
TEXT = (241, 245, 249)
MUTED = (148, 163, 184)
DIM = (100, 116, 139)
ACCENT = (56, 189, 248)
CYAN = (34, 211, 238)
VIOLET = (167, 139, 250)
AMBER = (251, 191, 36)

AR_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
]
LATIN_FONT_CANDIDATES = AR_FONT_CANDIDATES + ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"]


def _font(size: int, candidates) -> ImageFont.ImageFont:
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _radial_glow(
    size: Tuple[int, int], center: Tuple[int, int], radius: int, color: Tuple[int, int, int]
) -> Image.Image:
    """طبقة توهّج بشفافية متدرّجة (RGBA) لدمجها على الخلفية."""
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    steps = 26
    for i in range(steps, 0, -1):
        r = int(radius * i / steps)
        alpha = int(42 * (i / steps) ** 2)
        overlay = Image.new("RGBA", size, (0, 0, 0, 0))
        ImageDraw.Draw(overlay).ellipse(
            [center[0] - r, center[1] - r, center[0] + r, center[1] + r],
            fill=(color[0], color[1], color[2], alpha),
        )
        layer = Image.alpha_composite(layer, overlay)
    return layer.filter(ImageFilter.GaussianBlur(38))


def _load_logo(size: int) -> Optional[Image.Image]:
    """يجرّب تحويل الشعار SVG إلى صورة، أو يرسم علامة بديلة."""
    svg = os.path.join(IMG_DIR, "logo.svg")
    png_tmp = os.path.join(HERE, ".logo_tmp.png")
    if os.path.exists(svg):
        try:
            import cairosvg  # type: ignore

            cairosvg.svg2png(url=svg, write_to=png_tmp, output_width=size, output_height=size)
            return Image.open(png_tmp).convert("RGBA")
        except Exception:  # noqa: BLE001
            pass
        for cmd in (["rsvg-convert", "-w", str(size), "-h", str(size), "-o", png_tmp, svg],
                    ["inkscape", svg, "-w", str(size), "-h", str(size), "-o", png_tmp]):
            try:
                subprocess.run(cmd, check=True, capture_output=True)
                return Image.open(png_tmp).convert("RGBA")
            except Exception:  # noqa: BLE001
                continue
    # بديل مرسوم يحاكي logo.svg: حلقة + سداسي + شبكة داخلية
    ss = 4  # supersampling لجودة الحواف
    canvas = Image.new("RGBA", (size * ss, size * ss), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    n = size * ss
    ring = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse(
        [n * 0.06, n * 0.06, n * 0.94, n * 0.94], outline=(56, 189, 248, 120), width=int(n * 0.03)
    )
    canvas = Image.alpha_composite(canvas, ring)
    draw = ImageDraw.Draw(canvas)
    pad = n * 0.2
    hexa = [
        (n / 2, pad),
        (n - pad * 0.86, n * 0.36),
        (n - pad * 0.86, n * 0.64),
        (n / 2, n - pad),
        (pad * 0.86, n * 0.64),
        (pad * 0.86, n * 0.36),
    ]
    draw.polygon(hexa, fill=(56, 189, 248, 40), outline=CYAN, width=int(n * 0.028))
    apex = (n / 2, n * 0.36)
    left = (n * 0.37, n * 0.64)
    right = (n * 0.63, n * 0.64)
    width = int(n * 0.03)
    draw.line([left, apex, right], fill=(241, 245, 249, 255), width=width, joint="curve")
    draw.line([left, right], fill=(148, 163, 184, 220), width=int(width * 0.8))
    r = n * 0.035
    draw.ellipse([apex[0] - r, apex[1] - r, apex[0] + r, apex[1] + r], fill=(248, 250, 252, 255))
    r2 = n * 0.028
    draw.ellipse([left[0] - r2, left[1] - r2, left[0] + r2, left[1] + r2], fill=ACCENT + (255,))
    draw.ellipse([right[0] - r2, right[1] - r2, right[0] + r2, right[1] + r2], fill=VIOLET + (255,))
    return canvas.resize((size, size), Image.LANCZOS)


def _bar(draw: ImageDraw.ImageDraw, x: int, y: int, width: int, ratio: float,
         colors: Tuple[Tuple[int, int, int], Tuple[int, int, int]]) -> None:
    height = 9
    draw.rounded_rectangle([x, y, x + width, y + height], radius=5, fill=BORDER)
    fill_w = max(6, int(width * ratio))
    draw.rounded_rectangle([x, y, x + fill_w, y + height], radius=5, fill=colors[0])
    if ratio > 0.15:
        mid = x + int(fill_w * 0.6)
        draw.rounded_rectangle([mid, y, x + fill_w, y + height], radius=5, fill=colors[1])


def render(out_path: str = OUT_PATH) -> str:
    base = Image.new("RGBA", (W, H), BG + (255,))
    base = Image.alpha_composite(base, _radial_glow((W, H), (980, 90), 330, ACCENT))
    base = Image.alpha_composite(base, _radial_glow((W, H), (120, 580), 300, VIOLET))
    draw = ImageDraw.Draw(base, "RGBA")

    # الشعار والعنوان
    logo = _load_logo(74)
    if logo is not None:
        base.paste(logo, (72, 58), logo)
    title_font = _font(46, LATIN_FONT_CANDIDATES)
    sub_font = _font(17, AR_FONT_CANDIDATES)
    draw.text((162, 62), "Nonzra", font=title_font, fill=CYAN)
    draw.text((162, 118), "self-learning captcha mind · open source", font=sub_font, fill=DIM)

    head_font = _font(34, LATIN_FONT_CANDIDATES)
    body_font = _font(18, LATIN_FONT_CANDIDATES)
    draw.text((72, 178), "Learns from every attempt,", font=head_font, fill=TEXT)
    draw.text((72, 222), "and explains its decisions.", font=head_font, fill=ACCENT)
    draw.text(
        (72, 288),
        "Calibrated confidence · self-assessed competence per type",
        font=body_font,
        fill=MUTED,
    )
    draw.text(
        (72, 316),
        "expected-value planning · lessons learned from failures.",
        font=body_font,
        fill=MUTED,
    )

    # رقائق
    chip_font = _font(15, LATIN_FONT_CANDIDATES)
    chips = ["10 captcha types", "17 knowledge cards", "73 tests", "Docker"]
    x = 72
    for chip in chips:
        w = draw.textlength(chip, font=chip_font) + 26
        draw.rounded_rectangle([x, 372, x + w, 408], radius=18, fill=(56, 189, 248, 26),
                               outline=(56, 189, 248, 82))
        draw.text((x + 13, 381), chip, font=chip_font, fill=(125, 211, 252))
        x += w + 12

    # لوحة الحالة
    panel = [660, 96, 1130, 520]
    draw.rounded_rectangle(panel, radius=22, fill=CARD, outline=BORDER, width=1)
    panel_title = _font(17, LATIN_FONT_CANDIDATES)
    draw.text((688, 122), "Mind state · live", font=panel_title, fill=MUTED)
    draw.ellipse([1092, 126, 1102, 136], fill=CYAN)

    rows = [
        ("Image OCR", 0.92, (ACCENT, CYAN)),
        ("Math", 0.85, (VIOLET, (129, 140, 248))),
        ("Slider", 0.78, (ACCENT, CYAN)),
        ("Rotate", 0.71, (VIOLET, (129, 140, 248))),
        ("Turnstile", 0.34, (AMBER, (245, 158, 11))),
    ]
    label_font = _font(16, LATIN_FONT_CANDIDATES)
    small = _font(14, LATIN_FONT_CANDIDATES)
    y = 158
    for name, ratio, colors in rows:
        draw.text((688, y), name, font=label_font, fill=(203, 213, 225))
        pct = f"{int(ratio * 100)}%"
        draw.text((1064 - draw.textlength(pct, font=small), y + 2), pct, font=small, fill=MUTED)
        _bar(draw, 688, y + 26, 400, ratio, colors)
        y += 58

    # اقتباس
    quote_box = [680, 436, 1110, 498]
    draw.rounded_rectangle(quote_box, radius=12, fill=(56, 189, 248, 20), outline=(56, 189, 248, 76))
    draw.text((694, 448), "Strong at image OCR · weakest at Turnstile.", font=small,
              fill=(125, 211, 252))
    draw.text((694, 470), "Next experiment: preprocess parameter sweep.", font=small,
              fill=(125, 211, 252))

    foot = _font(14, LATIN_FONT_CANDIDATES)
    draw.text((72, 566), "github.com/azerty1112/Nonzra", font=foot, fill=(71, 85, 105))
    draw.text((1130 - draw.textlength("v0.7 · MIT", font=foot), 566), "v0.7 · MIT", font=foot,
              fill=(71, 85, 105))

    base.convert("RGB").save(out_path, optimize=True)
    tmp = os.path.join(HERE, ".logo_tmp.png")
    if os.path.exists(tmp):
        os.remove(tmp)
    return out_path


if __name__ == "__main__":
    print(render())
