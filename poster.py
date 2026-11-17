"""
poster.py
Template-based poster maker. Uses only Pillow, so it needs no AI model and
uses no API quota. Call make_poster(data, fmt) -> (bytes, extension).
"""
import io
import os
import re
import random
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ----------------------------------------------------------------------
# Options shown in the UI
# ----------------------------------------------------------------------
SIZES = {
    "portrait": (1080, 1350),   # Instagram / WhatsApp portrait
    "square":   (1080, 1080),
    "story":    (1080, 1920),   # Status / Story / Reel cover
    "a4":       (1240, 1754),   # print
}
SIZE_LIST = [
    {"id": "portrait", "name": "Portrait (4:5)"},
    {"id": "square",   "name": "Square (1:1)"},
    {"id": "story",    "name": "Story / Status (9:16)"},
    {"id": "a4",       "name": "A4 Print"},
]

TYPE_LABELS = {
    "event":    "YOU'RE INVITED",
    "sale":     "SPECIAL OFFER",
    "birthday": "LET'S CELEBRATE",
    "notice":   "IMPORTANT NOTICE",
    "quote":    "",
    "general":  "",
}

THEMES = {
    "midnight": dict(name="Midnight", c1="#0B0F17", c2="#1F2A44", accent="#5B8DEF", text="#FFFFFF", on_accent="#06090F", dark=True),
    "ocean":    dict(name="Ocean",    c1="#0B1F3A", c2="#0E7C86", accent="#5EEAD4", text="#FFFFFF", on_accent="#06222B", dark=True),
    "sunset":   dict(name="Sunset",   c1="#FF8A3D", c2="#B4125A", accent="#FFE66D", text="#FFFFFF", on_accent="#3B1A00", dark=True),
    "royal":    dict(name="Royal",    c1="#1E1B4B", c2="#6D28D9", accent="#FBBF24", text="#FFFFFF", on_accent="#2A1A00", dark=True),
    "forest":   dict(name="Forest",   c1="#052E16", c2="#15803D", accent="#BEF264", text="#FFFFFF", on_accent="#10260A", dark=True),
    "rose":     dict(name="Rose",     c1="#831843", c2="#F472B6", accent="#FDE68A", text="#FFFFFF", on_accent="#4A1230", dark=True),
    "gold":     dict(name="Black Gold", c1="#0F0F0F", c2="#3A2A00", accent="#F5C542", text="#FFFFFF", on_accent="#1A1200", dark=True),
    "light":    dict(name="Cream",    c1="#FFFBEB", c2="#FED7AA", accent="#EA580C", text="#1F2937", on_accent="#FFFFFF", dark=False),
}
THEME_LIST = [{"id": k, "name": v["name"], "c1": v["c1"], "c2": v["c2"]} for k, v in THEMES.items()]

# ----------------------------------------------------------------------
# Fonts (uses fonts already installed on the computer)
# ----------------------------------------------------------------------
_FONT_DIRS = [
    r"C:\Windows\Fonts",
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/liberation",
    "/usr/share/fonts/truetype/noto",
    "/Library/Fonts",
    "/System/Library/Fonts/Supplemental",
    "/System/Library/Fonts",
]
_FONT_CHOICES = {
    "bold":       ["segoeuib.ttf", "arialbd.ttf", "calibrib.ttf", "Arial Bold.ttf", "LiberationSans-Bold.ttf", "DejaVuSans-Bold.ttf"],
    "regular":    ["segoeui.ttf", "arial.ttf", "calibri.ttf", "Arial.ttf", "LiberationSans-Regular.ttf", "DejaVuSans.ttf"],
    "serif":      ["georgiai.ttf", "georgia.ttf", "timesi.ttf", "times.ttf", "LiberationSerif-Italic.ttf", "DejaVuSerif.ttf"],
    "hindi_bold": ["NirmalaB.ttf", "Nirmala.ttf", "mangalb.ttf", "mangal.ttf"],
    "hindi":      ["Nirmala.ttf", "mangal.ttf"],
}
_DEVANAGARI = re.compile(r"[\u0900-\u097F]")


@lru_cache(maxsize=256)
def _load_font(kind, size):
    for name in _FONT_CHOICES[kind]:
        for folder in _FONT_DIRS:
            path = os.path.join(folder, name)
            if os.path.isfile(path):
                try:
                    return ImageFont.truetype(path, size)
                except OSError:
                    continue
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def _font_for(text, kind, size):
    if _DEVANAGARI.search(text or ""):
        kind = "hindi_bold" if kind == "bold" else "hindi"
    return _load_font(kind, int(size))


# ----------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------
def _rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _clean(text, max_len):
    """Removes emoji / control characters (the poster fonts can't draw them) and limits length."""
    text = re.sub(r"[\U00010000-\U0010FFFF]", "", str(text or ""))
    text = re.sub(r"[^\S\n]+", " ", text)
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", text)
    lines = [ln.strip() for ln in text.split("\n")]
    return "\n".join(lines).strip()[:max_len]


def _wrap(d, text, font, max_w):
    lines = []
    for para in text.split("\n"):
        words = para.split()
        if not words:
            continue
        cur = ""
        for w in words:
            trial = (cur + " " + w).strip()
            if d.textlength(trial, font=font) <= max_w:
                cur = trial
                continue
            if cur:
                lines.append(cur)
            while len(w) > 1 and d.textlength(w, font=font) > max_w:
                k = len(w)
                while k > 1 and d.textlength(w[:k], font=font) > max_w:
                    k -= 1
                lines.append(w[:k])
                w = w[k:]
            cur = w
        if cur:
            lines.append(cur)
    return lines


def _fit(d, text, kind, max_w, max_h, start, minimum, spacing=1.18):
    """Largest font size (between start and minimum) at which the wrapped text fits max_h."""
    size = max(int(start), int(minimum))
    while True:
        font = _font_for(text, kind, size)
        lines = _wrap(d, text, font, max_w)
        h = int(len(lines) * size * spacing)
        if h <= max_h or size <= minimum:
            return font, lines, h, size
        size = max(int(minimum), int(size * 0.93))


def _spaced(d, cx, y, text, font, fill, spacing):
    widths = [d.textlength(ch, font=font) for ch in text]
    total = sum(widths) + spacing * (len(text) - 1)
    x = cx - total / 2
    for ch, w in zip(text, widths):
        d.text((x, y), ch, font=font, fill=fill, anchor="la")
        x += w + spacing
    return total


def _spaced_width(d, text, font, spacing):
    return sum(d.textlength(ch, font=font) for ch in text) + spacing * (len(text) - 1)


def _gradient(W, H, c1, c2):
    mask = Image.linear_gradient("L").resize((W, H))
    return Image.composite(Image.new("RGB", (W, H), c2), Image.new("RGB", (W, H), c1), mask)


def _glow(img, W, H, color, cx, cy, r, alpha):
    sw, sh = max(W // 4, 1), max(H // 4, 1)
    layer = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse(
        [cx / 4 - r / 4, cy / 4 - r / 4, cx / 4 + r / 4, cy / 4 + r / 4],
        fill=color + (alpha,),
    )
    layer = layer.filter(ImageFilter.GaussianBlur(max(r / 4 * 0.35, 1)))
    layer = layer.resize((W, H), Image.Resampling.BICUBIC)
    return Image.alpha_composite(img, layer)


# ----------------------------------------------------------------------
# The poster
# ----------------------------------------------------------------------
def make_poster(data, fmt="png"):
    """data keys: type, theme, size, title, subtitle, highlight, details,
    date, venue, contact.  Returns (bytes, 'png' | 'pdf')."""
    ptype = data.get("type") if data.get("type") in TYPE_LABELS else "general"
    th = THEMES.get(data.get("theme"), THEMES["midnight"])
    W, H = SIZES.get(data.get("size"), SIZES["portrait"])

    title = _clean(data.get("title"), 120)
    subtitle = _clean(data.get("subtitle"), 160)
    highlight = _clean(data.get("highlight"), 30)
    details = [ln for ln in _clean(data.get("details"), 600).split("\n") if ln][:8]
    date = _clean(data.get("date"), 80)
    venue = _clean(data.get("venue"), 120)
    contact = _clean(data.get("contact"), 160)
    label = TYPE_LABELS[ptype]

    c1, c2 = _rgb(th["c1"]), _rgb(th["c2"])
    acc, on_acc, txt = _rgb(th["accent"]), _rgb(th["on_accent"]), _rgb(th["text"])
    dim = txt + (205,)
    card_fill = (255, 255, 255, 34) if th["dark"] else (0, 0, 0, 14)

    img = _gradient(W, H, c1, c2).convert("RGBA")
    img = _glow(img, W, H, acc, int(W * 0.92), int(H * 0.07), int(W * 0.55), 95)
    img = _glow(img, W, H, acc, int(W * 0.04), int(H * 0.96), int(W * 0.50), 70)
    # Pillow only blends transparent colours when the image itself is RGB
    img = img.convert("RGB")
    d = ImageDraw.Draw(img, "RGBA")

    m = int(W * 0.095)            # side margin
    cw = W - 2 * m                # content width

    # confetti for birthday posters (only in the border area, never over the text)
    if ptype == "birthday":
        rng = random.Random(len(title) * 7 + W)
        edge = int(W * 0.035) + 16
        for _ in range(70):
            zone = rng.choice(["left", "right", "top", "bottom"])
            if zone == "left":
                x, y = rng.randint(edge, m - 14), rng.randint(edge, H - edge)
            elif zone == "right":
                x, y = rng.randint(W - m + 14, W - edge), rng.randint(edge, H - edge)
            elif zone == "top":
                x, y = rng.randint(edge, W - edge), rng.randint(edge, max(edge + 1, m - 14))
            else:
                x, y = rng.randint(edge, W - edge), rng.randint(H - m + 14, H - edge)
            r = rng.randint(5, 12)
            col = rng.choice([acc, txt, acc]) + (rng.randint(120, 210),)
            if rng.random() < 0.6:
                d.ellipse([x - r, y - r, x + r, y + r], fill=col)
            else:
                d.rounded_rectangle([x - r, y - r // 2, x + r, y + r // 2], radius=2, fill=col)

    # thin frame
    inset = int(W * 0.035)
    d.rounded_rectangle([inset, inset, W - inset, H - inset], radius=int(W * 0.04),
                        outline=acc + (110,), width=max(2, int(W * 0.003)))

    # ---- top label pill -------------------------------------------------
    top_end = m
    if label:
        lf = _load_font("bold", int(W * 0.027))
        sp = W * 0.006
        tw = _spaced_width(d, label, lf, sp)
        pad_x, pad_y = int(W * 0.035), int(W * 0.016)
        ph = int(W * 0.027) + 2 * pad_y
        pw = int(tw + 2 * pad_x)
        d.rounded_rectangle([(W - pw) / 2, m, (W + pw) / 2, m + ph], radius=ph // 2, fill=acc)
        _spaced(d, W / 2, m + pad_y - 2, label, lf, on_acc, sp)
        top_end = m + ph

    # ---- footer (contact) ------------------------------------------------
    footer_h = 0
    footer_lines, footer_font = [], None
    if contact:
        footer_font, footer_lines, fh, _ = _fit(d, contact, "regular", cw, int(H * 0.09), W * 0.03, W * 0.022, 1.25)
        footer_h = fh + int(W * 0.03)
    bottom_limit = H - m - footer_h
    gap_top = int(W * 0.04)
    area_top = top_end + gap_top
    area_h = max(bottom_limit - gap_top - area_top, 100)

    if footer_lines:
        fy = H - m - (footer_h - int(W * 0.03))
        d.rounded_rectangle([W / 2 - W * 0.07, fy - int(W * 0.022), W / 2 + W * 0.07, fy - int(W * 0.022) + 3],
                            radius=2, fill=acc + (150,))
        for ln in footer_lines:
            d.text((W / 2, fy), ln, font=footer_font, fill=dim, anchor="ma")
            fy += int(footer_font.size * 1.25)

    # ---- content blocks ----------------------------------------------------
    def build(s):
        blocks = []   # (height, draw(y), gap_after)
        gap = int(W * 0.038 * s)

        if ptype == "quote":
            qs = int(W * 0.26 * s)
            qf = _load_font("serif", qs)
            blocks.append((int(qs * 0.5), lambda y, qf=qf, qs=qs: d.text((W / 2, y - int(qs * 0.2)), "\u201C", font=qf, fill=acc, anchor="ma"), int(gap * 0.2)))
            f, lines, h, size = _fit(d, title or "Your quote here", "serif", cw, int(area_h * 0.6 * s), W * 0.085 * s, W * 0.032, 1.28)

            def draw_quote(y, f=f, lines=lines, size=size):
                for ln in lines:
                    d.text((W / 2, y), ln, font=f, fill=txt, anchor="ma")
                    y += int(size * 1.28)
            blocks.append((h, draw_quote, gap))
            blocks.append((int(W * 0.008) + 4, lambda y: d.rounded_rectangle([W / 2 - W * 0.08, y, W / 2 + W * 0.08, y + max(4, int(W * 0.008))], radius=3, fill=acc), gap))
            if subtitle:
                f, lines, h, size = _fit(d, "\u2014 " + subtitle, "bold", cw, int(area_h * 0.15), W * 0.042 * s, W * 0.026)

                def draw_author(y, f=f, lines=lines, size=size):
                    for ln in lines:
                        d.text((W / 2, y), ln, font=f, fill=acc, anchor="ma")
                        y += int(size * 1.18)
                blocks.append((h, draw_author, gap))
            return blocks

        # highlight badge (e.g. "50% OFF")
        if highlight:
            f, lines, h, size = _fit(d, highlight, "bold", int(cw * 0.78), int(area_h * 0.2), W * 0.13 * s, W * 0.05, 1.1)
            padx, pady = int(W * 0.05), int(W * 0.026)
            tw = max(d.textlength(ln, font=f) for ln in lines)
            bw, bh = int(tw + 2 * padx), h + 2 * pady

            def draw_badge(y, f=f, lines=lines, size=size, bw=bw, bh=bh, pady=pady):
                d.rounded_rectangle([(W - bw) / 2, y, (W + bw) / 2, y + bh], radius=int(W * 0.03), fill=acc)
                yy = y + pady
                for ln in lines:
                    d.text((W / 2, yy), ln, font=f, fill=on_acc, anchor="ma")
                    yy += int(size * 1.1)
            blocks.append((bh, draw_badge, gap))

        # title
        f, lines, h, size = _fit(d, title or "Your title", "bold", cw, int(area_h * 0.36 * s), W * 0.12 * s, W * 0.045, 1.12)

        def draw_title(y, f=f, lines=lines, size=size):
            for ln in lines:
                d.text((W / 2, y), ln, font=f, fill=txt, anchor="ma")
                y += int(size * 1.12)
        blocks.append((h, draw_title, gap))

        # divider
        bar_h = max(5, int(W * 0.009))
        blocks.append((bar_h, lambda y: d.rounded_rectangle([W / 2 - W * 0.09, y, W / 2 + W * 0.09, y + bar_h], radius=bar_h // 2, fill=acc), gap))

        # subtitle
        if subtitle:
            f, lines, h, size = _fit(d, subtitle, "regular", int(cw * 0.94), int(area_h * 0.2 * s), W * 0.05 * s, W * 0.026, 1.25)

            def draw_sub(y, f=f, lines=lines, size=size):
                for ln in lines:
                    d.text((W / 2, y), ln, font=f, fill=dim, anchor="ma")
                    y += int(size * 1.25)
            blocks.append((h, draw_sub, gap))

        # bullet details
        if details:
            max_h = int(area_h * 0.3 * s)
            size = int(W * 0.04 * s)
            min_size = int(W * 0.024)
            while True:
                f = _load_font("regular", size)
                wrapped = [_wrap(d, ln, f, int(cw * 0.82)) or [ln] for ln in details]
                total = sum(len(w) for w in wrapped)
                h = int(total * size * 1.3 + (len(wrapped) - 1) * size * 0.25)
                if h <= max_h or size <= min_size:
                    break
                size = max(min_size, int(size * 0.93))
            widest = max(d.textlength(x, font=f) for w in wrapped for x in w)
            bullet = int(size * 0.55)

            def draw_details(y, f=f, wrapped=wrapped, size=size, widest=widest, bullet=bullet):
                x0 = (W - (widest + bullet * 2)) / 2
                for w in wrapped:
                    r = max(4, int(size * 0.14))
                    d.ellipse([x0, y + size * 0.52 - r, x0 + 2 * r, y + size * 0.52 + r], fill=acc)
                    yy = y
                    for ln in w:
                        d.text((x0 + bullet * 2 - r, yy), ln, font=f, fill=txt, anchor="la")
                        yy += int(size * 1.3)
                    y = yy + int(size * 0.25)
            blocks.append((h, draw_details, gap))

        # info cards
        for lab, val in (("DATE & TIME", date), ("VENUE", venue)):
            if not val:
                continue
            pad = int(W * 0.03)
            lf = _load_font("bold", int(W * 0.022 * s))
            vf, vlines, vh, vsize = _fit(d, val, "bold", cw - 2 * pad, int(area_h * 0.14), W * 0.04 * s, W * 0.026, 1.2)
            ch = pad + int(lf.size * 1.3) + vh + pad

            def draw_card(y, lab=lab, lf=lf, vf=vf, vlines=vlines, vsize=vsize, ch=ch, pad=pad):
                d.rounded_rectangle([m, y, W - m, y + ch], radius=int(W * 0.03), fill=card_fill, outline=acc + (95,), width=2)
                _spaced(d, W / 2, y + pad, lab, lf, acc, W * 0.004)
                yy = y + pad + int(lf.size * 1.3)
                for ln in vlines:
                    d.text((W / 2, yy), ln, font=vf, fill=txt, anchor="ma")
                    yy += int(vsize * 1.2)
            blocks.append((ch, draw_card, int(gap * 0.45)))

        return blocks

    scale = 1.0
    for _ in range(14):
        blocks = build(scale)
        total = sum(b[0] for b in blocks) + sum(b[2] for b in blocks[:-1])
        if total <= area_h or scale < 0.4:
            break
        scale *= 0.92

    y = area_top + max((area_h - total) // 2, 0)
    for i, (h, draw, gap_after) in enumerate(blocks):
        draw(y)
        y += h + (gap_after if i < len(blocks) - 1 else 0)

    out = io.BytesIO()
    if fmt == "pdf":
        img.save(out, format="PDF", resolution=150.0)
        return out.getvalue(), "pdf"
    img.save(out, format="PNG", optimize=True)
    return out.getvalue(), "png"