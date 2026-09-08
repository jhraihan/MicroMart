"""
Generated placeholder product artwork.

**Why generate rather than download.** Real product photography on a retail
site is the photographer's or the manufacturer's work, and re-hosting it is a
copyright problem regardless of how the demo catalogue is described. So this
module draws its own images with Pillow: a soft two-tone panel, the brand
initials, a category glyph and the model line. They are unmistakably
placeholders, they are ours, and they make a 111-product catalogue look like a
populated store rather than a wall of grey boxes.

The output is deterministic. Colour and glyph are derived from the product
slug, so re-running the seeder produces byte-identical files and does not
churn the media directory or invalidate a browser cache.

Sizes follow what the storefront actually asks for: a 900x900 primary for the
detail gallery, which the cards downscale. One image per product plus two
angle variations, so the gallery has something to page through.
"""
import hashlib
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

# Square, because a product grid with mixed aspect ratios never lines up.
IMAGE_SIZE = 900

# Muted panel colours. Each is a (top, bottom) pair for the vertical wash, and
# all of them are light enough that the dark label text on top clears WCAG AA.
PALETTES = [
    ((238, 242, 248), (214, 224, 238)),
    ((243, 240, 234), (226, 219, 205)),
    ((234, 243, 240), (206, 228, 221)),
    ((242, 236, 243), (223, 210, 228)),
    ((240, 238, 232), (219, 215, 203)),
    ((235, 240, 245), (210, 222, 234)),
    ((245, 238, 236), (230, 214, 210)),
]

# A simple line glyph per builder slot / category family. Drawn from
# primitives rather than shipped as assets so there is nothing to license and
# nothing to lose.
GLYPHS = {
    "cpu": "chip",
    "processor": "chip",
    "motherboard": "board",
    "graphics-card": "card",
    "ram": "stick",
    "ssd": "stick",
    "hard-disk-drive": "disc",
    "power-supply": "box",
    "pc-case": "tower",
    "cpu-cooler": "fan",
    "monitor": "screen",
    "gaming-monitor": "screen",
    "office-monitor": "screen",
    "tv": "screen",
    "projector": "screen",
    "laptop": "laptop",
    "gaming-laptop": "laptop",
    "ultrabook": "laptop",
    "business-laptop": "laptop",
    "mobile-phone": "phone",
    "tablet": "phone",
    "smart-watch": "watch",
    "keyboard": "keys",
    "mouse": "mouse",
    "headphone": "headphone",
    "speaker": "speaker",
    "microphone": "mic",
    "webcam": "camera",
    "camera": "camera",
    "action-camera": "camera",
    "mirrorless-camera": "camera",
    "router": "signal",
    "network-switch": "box",
    "network-adapter": "signal",
    "printer": "printer",
    "inkjet-printer": "printer",
    "laser-printer": "printer",
}

DEFAULT_GLYPH = "box"

# Ink colours for the label text -- both well past 4.5:1 on every palette above.
INK = (33, 33, 33)
INK_MUTED = (90, 96, 104)


def _seed(slug):
    """A stable integer per product, so artwork never changes between runs."""
    return int(hashlib.sha256(slug.encode("utf-8")).hexdigest()[:8], 16)


def _font(size, bold=False):
    """
    A real TrueType face when the platform has one, Pillow's bitmap font
    otherwise.

    The fallback is deliberately not an error: the seeder must run on a bare
    CI container with no system fonts, and a slightly uglier placeholder is a
    far better outcome than a seed that refuses to complete.
    """
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold
        else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf" if bold else "C:\\Windows\\Fonts\\arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _gradient(size, top, bottom):
    """Vertical two-tone wash, drawn a row at a time."""
    image = Image.new("RGB", (size, size), top)
    draw = ImageDraw.Draw(image)
    for y in range(size):
        ratio = y / max(size - 1, 1)
        draw.line(
            [(0, y), (size, y)],
            fill=(
                int(top[0] + (bottom[0] - top[0]) * ratio),
                int(top[1] + (bottom[1] - top[1]) * ratio),
                int(top[2] + (bottom[2] - top[2]) * ratio),
            ),
        )
    return image


def _draw_glyph(draw, kind, box, colour):
    """
    A simple outline mark, drawn from rectangles and ellipses.

    Each branch is a handful of primitives -- enough to read as "this is a
    graphics card" at card size, and honest about being a placeholder at full
    size.
    """
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    line = max(4, w // 40)

    if kind == "chip":
        draw.rounded_rectangle([x0, y0, x1, y1], radius=w // 12, outline=colour, width=line)
        inner = w // 5
        draw.rounded_rectangle(
            [x0 + inner, y0 + inner, x1 - inner, y1 - inner],
            radius=w // 20, outline=colour, width=line,
        )
        for i in range(1, 5):
            step = y0 + h * i / 5
            draw.line([(x0 - w // 10, step), (x0, step)], fill=colour, width=line)
            draw.line([(x1, step), (x1 + w // 10, step)], fill=colour, width=line)

    elif kind == "board":
        draw.rounded_rectangle([x0, y0, x1, y1], radius=w // 20, outline=colour, width=line)
        draw.rounded_rectangle(
            [x0 + w // 8, y0 + h // 8, x0 + w // 2, y0 + h // 2],
            radius=w // 30, outline=colour, width=line,
        )
        for i in range(3):
            top = y0 + h * (0.62 + i * 0.11)
            draw.line([(x0 + w // 8, top), (x1 - w // 8, top)], fill=colour, width=line)

    elif kind == "card":
        draw.rounded_rectangle(
            [x0, y0 + h // 6, x1, y1 - h // 6], radius=w // 25, outline=colour, width=line
        )
        for cx in (x0 + w // 3, x0 + 2 * w // 3):
            r = w // 7
            draw.ellipse([cx - r, y0 + h // 2 - r, cx + r, y0 + h // 2 + r],
                         outline=colour, width=line)

    elif kind == "stick":
        draw.rounded_rectangle(
            [x0, y0 + h // 3, x1, y1 - h // 3], radius=w // 40, outline=colour, width=line
        )
        for i in range(1, 6):
            cx = x0 + w * i / 6
            draw.line([(cx, y0 + h // 3), (cx, y1 - h // 3)], fill=colour, width=line // 2 or 1)

    elif kind == "disc":
        draw.ellipse([x0, y0, x1, y1], outline=colour, width=line)
        r = w // 6
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=colour, width=line)

    elif kind == "tower":
        draw.rounded_rectangle(
            [x0 + w // 5, y0, x1 - w // 5, y1], radius=w // 25, outline=colour, width=line
        )
        for i in range(3):
            top = y0 + h * (0.15 + i * 0.12)
            draw.line([(x0 + w // 3, top), (x1 - w // 3, top)], fill=colour, width=line)

    elif kind == "fan":
        draw.ellipse([x0, y0, x1, y1], outline=colour, width=line)
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        r = w // 8
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=colour, width=line)
        for angle in (0, 90, 180, 270):
            import math
            rad = math.radians(angle)
            draw.line(
                [(cx + r * math.cos(rad), cy + r * math.sin(rad)),
                 (cx + (w // 2 - line) * math.cos(rad), cy + (w // 2 - line) * math.sin(rad))],
                fill=colour, width=line,
            )

    elif kind == "screen":
        draw.rounded_rectangle(
            [x0, y0, x1, y1 - h // 4], radius=w // 30, outline=colour, width=line
        )
        draw.line([((x0 + x1) // 2, y1 - h // 4), ((x0 + x1) // 2, y1 - h // 12)],
                  fill=colour, width=line)
        draw.line([(x0 + w // 4, y1), (x1 - w // 4, y1)], fill=colour, width=line)

    elif kind == "laptop":
        draw.rounded_rectangle(
            [x0 + w // 10, y0, x1 - w // 10, y1 - h // 3], radius=w // 40,
            outline=colour, width=line,
        )
        draw.rounded_rectangle(
            [x0, y1 - h // 4, x1, y1 - h // 8], radius=w // 60, outline=colour, width=line
        )

    elif kind == "phone":
        draw.rounded_rectangle(
            [x0 + w // 4, y0, x1 - w // 4, y1], radius=w // 12, outline=colour, width=line
        )
        draw.line([(x0 + w // 2.6, y0 + h // 12), (x1 - w // 2.6, y0 + h // 12)],
                  fill=colour, width=line)

    elif kind == "watch":
        draw.rounded_rectangle(
            [x0 + w // 4, y0 + h // 4, x1 - w // 4, y1 - h // 4], radius=w // 10,
            outline=colour, width=line,
        )
        draw.line([((x0 + x1) // 2, y0), ((x0 + x1) // 2, y0 + h // 4)], fill=colour, width=line * 2)
        draw.line([((x0 + x1) // 2, y1 - h // 4), ((x0 + x1) // 2, y1)], fill=colour, width=line * 2)

    elif kind == "keys":
        draw.rounded_rectangle([x0, y0 + h // 4, x1, y1 - h // 4], radius=w // 30,
                               outline=colour, width=line)
        for row in range(2):
            for col in range(5):
                kx = x0 + w * (0.1 + col * 0.17)
                ky = y0 + h * (0.36 + row * 0.16)
                draw.rectangle([kx, ky, kx + w * 0.1, ky + h * 0.1], outline=colour, width=line // 2 or 1)

    elif kind == "mouse":
        draw.rounded_rectangle(
            [x0 + w // 4, y0, x1 - w // 4, y1], radius=w // 4, outline=colour, width=line
        )
        draw.line([((x0 + x1) // 2, y0 + h // 8), ((x0 + x1) // 2, y0 + h // 3)],
                  fill=colour, width=line)

    elif kind == "headphone":
        draw.arc([x0, y0, x1, y1], start=180, end=360, fill=colour, width=line * 2)
        ear = w // 6
        draw.rounded_rectangle([x0, (y0 + y1) // 2 - ear // 2, x0 + ear, (y0 + y1) // 2 + ear],
                               radius=ear // 3, outline=colour, width=line)
        draw.rounded_rectangle([x1 - ear, (y0 + y1) // 2 - ear // 2, x1, (y0 + y1) // 2 + ear],
                               radius=ear // 3, outline=colour, width=line)

    elif kind == "speaker":
        draw.rounded_rectangle([x0 + w // 4, y0, x1 - w // 4, y1], radius=w // 25,
                               outline=colour, width=line)
        r = w // 8
        cx = (x0 + x1) // 2
        draw.ellipse([cx - r, y0 + h // 4 - r, cx + r, y0 + h // 4 + r], outline=colour, width=line)
        r2 = w // 5
        draw.ellipse([cx - r2, y1 - h // 3 - r2, cx + r2, y1 - h // 3 + r2], outline=colour, width=line)

    elif kind == "mic":
        draw.rounded_rectangle(
            [x0 + w // 3, y0, x1 - w // 3, y0 + h * 0.55], radius=w // 6,
            outline=colour, width=line,
        )
        draw.arc([x0 + w // 5, y0 + h * 0.3, x1 - w // 5, y0 + h * 0.8],
                 start=0, end=180, fill=colour, width=line)
        draw.line([((x0 + x1) // 2, y0 + h * 0.8), ((x0 + x1) // 2, y1)], fill=colour, width=line)

    elif kind == "camera":
        draw.rounded_rectangle([x0, y0 + h // 5, x1, y1], radius=w // 20,
                               outline=colour, width=line)
        r = w // 5
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2 + h // 10
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=colour, width=line)
        draw.rectangle([x0 + w // 5, y0, x0 + w // 2, y0 + h // 5], outline=colour, width=line)

    elif kind == "signal":
        cx, cy = (x0 + x1) // 2, y1
        for i in range(1, 4):
            r = w * i / 6
            draw.arc([cx - r, cy - r, cx + r, cy + r], start=200, end=340, fill=colour, width=line)
        draw.ellipse([cx - line, cy - line, cx + line, cy + line], fill=colour)

    elif kind == "printer":
        draw.rounded_rectangle([x0, y0 + h // 3, x1, y1 - h // 5], radius=w // 30,
                               outline=colour, width=line)
        draw.rectangle([x0 + w // 5, y0, x1 - w // 5, y0 + h // 3], outline=colour, width=line)
        draw.rectangle([x0 + w // 5, y1 - h // 5, x1 - w // 5, y1], outline=colour, width=line)

    else:  # "box"
        draw.rounded_rectangle([x0, y0, x1, y1], radius=w // 20, outline=colour, width=line)
        draw.line([(x0, y0 + h // 3), (x1, y0 + h // 3)], fill=colour, width=line)


def _fit(draw, text, font_size, max_width, bold=False):
    """Shrink a font until the text fits, so a long name never overflows."""
    size = font_size
    while size > 12:
        font = _font(size, bold=bold)
        if draw.textlength(text, font=font) <= max_width:
            return font
        size -= 2
    return _font(12, bold=bold)


def render_product_image(*, slug, name, brand, category_slug, accent, angle=0):
    """
    Draw one placeholder and return it as PNG bytes.

    `angle` distinguishes the gallery's extra shots -- same product, nudged
    composition -- so a detail page has more than one thumbnail without
    pretending to be a second photograph.
    """
    seed = _seed(slug) + angle * 7919
    top, bottom = PALETTES[seed % len(PALETTES)]
    image = _gradient(IMAGE_SIZE, top, bottom)
    draw = ImageDraw.Draw(image)

    accent_rgb = tuple(int(accent.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))

    # Glyph, nudged per angle so the three shots are visibly different.
    span = int(IMAGE_SIZE * 0.42)
    cx = IMAGE_SIZE // 2 + (angle - 1) * int(IMAGE_SIZE * 0.04)
    cy = int(IMAGE_SIZE * 0.44)
    box = (cx - span // 2, cy - span // 2, cx + span // 2, cy + span // 2)
    _draw_glyph(draw, GLYPHS.get(category_slug, DEFAULT_GLYPH), box, accent_rgb)

    # Brand chip, top left.
    initials = "".join(part[0] for part in brand.split()[:2]).upper()
    chip = int(IMAGE_SIZE * 0.11)
    margin = int(IMAGE_SIZE * 0.06)
    draw.rounded_rectangle(
        [margin, margin, margin + chip, margin + chip], radius=chip // 4, fill=accent_rgb
    )
    chip_font = _font(int(chip * 0.45), bold=True)
    tw = draw.textlength(initials, font=chip_font)
    draw.text(
        (margin + chip / 2 - tw / 2, margin + chip / 2 - chip * 0.28),
        initials, font=chip_font, fill=(255, 255, 255),
    )

    # Label block, lower third.
    text_width = IMAGE_SIZE - margin * 2
    brand_font = _fit(draw, brand.upper(), int(IMAGE_SIZE * 0.045), text_width, bold=True)
    draw.text((margin, int(IMAGE_SIZE * 0.72)), brand.upper(), font=brand_font, fill=accent_rgb)

    # Product name over at most two lines.
    words, lines, current = name.split(), [], ""
    name_font = _font(int(IMAGE_SIZE * 0.055), bold=True)
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=name_font) <= text_width:
            current = candidate
        else:
            lines.append(current)
            current = word
        if len(lines) == 2:
            break
    if current and len(lines) < 2:
        lines.append(current)
    if len(lines) == 2 and draw.textlength(lines[1], font=name_font) > text_width * 0.92:
        lines[1] = lines[1][:28].rstrip() + "..."

    y = int(IMAGE_SIZE * 0.78)
    for line in lines:
        draw.text((margin, y), line, font=name_font, fill=INK)
        y += int(IMAGE_SIZE * 0.065)

    draw.text(
        (margin, int(IMAGE_SIZE * 0.93)),
        "Representative image",
        font=_font(int(IMAGE_SIZE * 0.028)),
        fill=INK_MUTED,
    )

    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def render_category_tile(*, name, accent):
    """A small square tile for the category strip and the homepage grid."""
    size = 240
    image = _gradient(size, (245, 247, 250), (226, 232, 240))
    draw = ImageDraw.Draw(image)
    accent_rgb = tuple(int(accent.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    initial = name.strip()[:1].upper()
    font = _font(110, bold=True)
    tw = draw.textlength(initial, font=font)
    draw.ellipse([size * 0.18, size * 0.14, size * 0.82, size * 0.78], outline=accent_rgb, width=6)
    draw.text((size / 2 - tw / 2, size * 0.24), initial, font=font, fill=accent_rgb)
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def render_brand_logo(*, name, accent):
    """A wordmark tile for the brand strip. Ours, not the manufacturer's."""
    width, height = 320, 160
    image = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    accent_rgb = tuple(int(accent.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    font = _fit(draw, name, 46, width - 40, bold=True)
    tw = draw.textlength(name, font=font)
    draw.text(((width - tw) / 2, height / 2 - 30), name, font=font, fill=accent_rgb)
    draw.line([(width * 0.3, height * 0.74), (width * 0.7, height * 0.74)],
              fill=accent_rgb, width=4)
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
