#!/usr/bin/env python3
"""Render a branded LinkedIn card locally: typeset hook + geometric motif.
No API, no cost, crisp text, deterministic.

  python make_card.py                    # latest draft's hook
  python make_card.py "custom line"
  python make_card.py --motif gates      # force a motif
"""
from __future__ import annotations

import hashlib
import math
import pathlib
import sys
import textwrap
from datetime import datetime

import random

from PIL import Image, ImageChops, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent
MEDIA = ROOT / "media"

W, H = 1200, 628
INK     = (8, 8, 10)
INK_2   = (16, 16, 20)
INK_3   = (30, 30, 36)
PAPER   = (247, 247, 243)
CRIMSON = (215, 25, 32)
NAVY    = (30, 78, 130)
MUTED   = (132, 132, 140)

DISPLAY = ["C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf",
           "/usr/share/fonts/truetype/lato/Lato-Bold.ttf",
           "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
MONO    = ["C:/Windows/Fonts/consola.ttf", "C:/Windows/Fonts/cour.ttf",
           "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"]

MOTIFS = ("lattice", "boundary", "gates", "split", "orbit")



CRIMSON_D = (150, 16, 24)
NAVY_D    = (14, 42, 74)


def _slices(img, d, seed: int):
    """Hard-edged angular colour fields across the background.

    Straight cuts, flat fills, no gradients - the look of cut paper rather than
    a render. Angles and offsets vary by seed so no two cards share a layout,
    which is what stops a feed of these reading as a template.
    """
    rnd = random.Random(seed)
    layer = Image.new("RGB", (W, H), INK)
    ld = ImageDraw.Draw(layer)

    # A few diagonal bands sweeping across the frame, weighted to the right so
    # the text column stays quiet.
    bands = [
        (CRIMSON_D, rnd.uniform(0.46, 0.60), rnd.uniform(0.10, 0.20)),
        (NAVY_D,    rnd.uniform(0.62, 0.78), rnd.uniform(0.12, 0.24)),
        (INK_3,     rnd.uniform(0.28, 0.42), rnd.uniform(0.08, 0.16)),
    ]
    rnd.shuffle(bands)
    skew = rnd.uniform(0.30, 0.55) * (1 if rnd.random() < 0.5 else -1)

    for col, start, width in bands:
        x = start * W
        w = width * W
        dx = skew * H
        ld.polygon([(x, 0), (x + w, 0), (x + w + dx, H), (x + dx, H)], fill=col)

    # One thin crimson cut, full bleed - the accent that ties it to the brand.
    x = rnd.uniform(0.20, 0.34) * W
    dx = skew * H
    ld.polygon([(x, 0), (x + 9, 0), (x + 9 + dx, H), (x + dx, H)], fill=CRIMSON)

    img.paste(Image.blend(img, layer, 0.92), (0, 0))


def _grain(img, seed: int, amount: int = 9):
    """Fine monochrome grain. Kills the flat digital sheen; reads as print."""
    rnd = random.Random(seed + 7)
    noise = Image.new("L", (W // 2, H // 2))
    noise.putdata([128 + rnd.randint(-amount, amount) for _ in range((W // 2) * (H // 2))])
    noise = noise.resize((W, H), Image.BILINEAR).convert("RGB")
    return ImageChops.overlay(img, noise)


def font(paths, size):
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


# ---------------------------------------------------------------- motifs
# Each draws into the box (x0,y0,x1,y1). Abstract, never literal: shapes that
# read as boundary, gate, break, orbit. One crimson element per motif, never
# more - the accent stops being an accent the moment there are two.


def _lattice(d, box):
    """Radial lattice: spokes from a centre, joined by concentric chords, one
    crimson node where two lines meet. Original geometry - reads as a network
    under tension, which is what most of these posts are about."""
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    rings = (54, 96, 138, 176)
    spokes = 8
    angs = [math.radians(-90 + i * (360 / spokes)) for i in range(spokes)]

    for a in angs:
        d.line([(cx, cy),
                (cx + rings[-1] * math.cos(a), cy + rings[-1] * math.sin(a))],
               fill=INK_3, width=2)

    for ri, r in enumerate(rings):
        pts = [(cx + r * math.cos(a), cy + r * math.sin(a)) for a in angs]
        col = PAPER if ri == 1 else INK_3
        wdt = 3 if ri == 1 else 2
        for i in range(spokes):
            d.line([pts[i], pts[(i + 1) % spokes]], fill=col, width=wdt)

    a, r = angs[1], rings[1]
    nx, ny = cx + r * math.cos(a), cy + r * math.sin(a)
    d.ellipse([nx - 14, ny - 14, nx + 14, ny + 14], fill=CRIMSON)


def _boundary(d, box):
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    d.line([(cx, y0 + 6), (cx, y1 - 6)], fill=(58, 58, 68), width=4)
    r = 17
    d.ellipse([cx - 118 - r, cy - r, cx - 118 + r, cy + r], outline=PAPER, width=3)
    s = 46
    d.rounded_rectangle([cx + 74, cy - s, cx + 74 + 2 * s, cy + s],
                        radius=8, outline=PAPER, width=3)
    d.ellipse([cx + 74 + s - r, cy - r, cx + 74 + s + r, cy + r], fill=CRIMSON)


def _gates(d, box):
    x0, y0, x1, y1 = box
    n, gap = 8, 30
    total = (n - 1) * gap
    sx = (x0 + x1) // 2 - total // 2
    for i in range(n):
        x = sx + i * gap
        h = 96 if i % 2 == 0 else 128
        c = CRIMSON if i == 5 else INK_3
        wdt = 7 if i == 5 else 5
        d.line([(x, (y0 + y1) // 2 - h // 2), (x, (y0 + y1) // 2 + h // 2)],
               fill=c, width=wdt)
    d.line([(sx - 34, (y0 + y1) // 2), (sx + total + 34, (y0 + y1) // 2)],
           fill=PAPER, width=2)


def _split(d, box):
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    w, h = 210, 30
    d.rounded_rectangle([cx - w, cy - 78, cx + w, cy - 78 + h], radius=6,
                        outline=PAPER, width=3)
    d.rounded_rectangle([cx - w, cy + 48, cx - 26, cy + 48 + h], radius=6,
                        outline=PAPER, width=3)
    d.rounded_rectangle([cx + 26, cy + 48, cx + w, cy + 48 + h], radius=6,
                        outline=INK_3, width=3)
    d.line([(cx, cy - 22), (cx, cy + 26)], fill=CRIMSON, width=5)


def _orbit(d, box):
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    for i, r in enumerate((62, 104, 146)):
        d.ellipse([cx - r, cy - r, cx + r, cy + r],
                  outline=(PAPER if i == 0 else INK_3), width=3)
    a = math.radians(-38)
    nx, ny = cx + 104 * math.cos(a), cy + 104 * math.sin(a)
    d.ellipse([nx - 15, ny - 15, nx + 15, ny + 15], fill=CRIMSON)


DRAW = {"lattice": _lattice, "boundary": _boundary, "gates": _gates, "split": _split, "orbit": _orbit}


def pick_motif(text: str) -> str:
    """Deterministic but varied: the same hook always gets the same motif,
    different hooks spread across the set."""
    low = text.lower()
    for word, m in (("network", "lattice"), ("system", "lattice"),
                    ("agent", "lattice"), ("pipeline", "lattice"),
                    ("gate", "gates"), ("boundary", "boundary"),
                    ("switch", "boundary"), ("off", "boundary"),
                    ("break", "split"), ("split", "split"),
                    ("loop", "orbit"), ("cycle", "orbit")):
        if word in low:
            return m
    h = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
    return MOTIFS[h % len(MOTIFS)]


def hook_of_latest() -> str:
    drafts = sorted((ROOT / "drafts").glob("*.md"), key=lambda p: p.stat().st_mtime)
    if not drafts:
        sys.exit("No drafts found.")
    body = drafts[-1].read_text(encoding="utf-8").split("\n---", 1)[0]
    for line in body.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    sys.exit("Could not find a hook line.")


def render(text: str, out: pathlib.Path, motif: str | None = None) -> pathlib.Path:
    seed = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
    img = Image.new("RGB", (W, H), INK)
    d = ImageDraw.Draw(img)
    _slices(img, d, seed)
    d = ImageDraw.Draw(img)

    m = 44
    # Panel edge, drawn as an outline so the slices stay visible through it.
    d.rounded_rectangle([m, m, W - m, H - m], radius=12, outline=(52, 52, 62), width=2)

    # Scrim behind the text column: flat, hard-edged, keeps the hook readable
    # over whatever the slices did. Slightly off-vertical so it feels placed.
    scrim = Image.new("RGB", (W, H), INK)
    sd = ImageDraw.Draw(scrim)
    sd.polygon([(m + 6, m + 6), (m + 700, m + 6),
                (m + 672, H - m - 6), (m + 6, H - m - 6)], fill=INK)
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).polygon([(m + 6, m + 6), (m + 700, m + 6),
                                  (m + 672, H - m - 6), (m + 6, H - m - 6)], fill=222)
    img.paste(Image.composite(scrim, img, mask), (0, 0))
    d = ImageDraw.Draw(img)

    pad = 56
    text_x = m + pad
    text_w = 560                       # left column; motif sits to the right
    motif_box = (m + pad + text_w + 28, m + 74, W - m - 34, H - m - 96)

    DRAW[motif or pick_motif(text)](d, motif_box)

    d.rectangle([text_x, m + 62, text_x + 88, m + 62 + 6], fill=CRIMSON)

    size = 46
    while size > 22:
        f = font(DISPLAY, size)
        avg = d.textlength("n", font=f) or size * 0.5
        lines = textwrap.wrap(text, width=max(14, int(text_w / avg)))
        lh = int(size * 1.33)
        if len(lines) * lh <= H - 2 * m - 210:
            break
        size -= 3
    f = font(DISPLAY, size)

    y = m + 62 + 6 + 40
    for line in lines[:8]:
        d.text((text_x, y), line, font=f, fill=PAPER)
        y += lh

    fy = H - m - 58
    d.line([(text_x, fy), (W - m - pad, fy)], fill=(42, 42, 50), width=1)
    fm = font(MONO, 20)
    d.text((text_x, fy + 19), "webbyzain.online", font=fm, fill=MUTED)
    tick = "///"
    d.text((W - m - pad - d.textlength(tick, font=fm), fy + 19), tick,
           font=fm, fill=CRIMSON)

    img = _grain(img, seed)
    MEDIA.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)
    return out


if __name__ == "__main__":
    argv = sys.argv[1:]
    motif = None
    if "--motif" in argv:
        i = argv.index("--motif")
        motif = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    args = [a for a in argv if not a.startswith("--")]
    text = args[0] if args else hook_of_latest()
    out = render(text, MEDIA / f"{datetime.now():%Y-%m-%d}.png", motif)
    print(f"wrote {out}  ({out.stat().st_size // 1024} KB)")
