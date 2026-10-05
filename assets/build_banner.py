"""Build the README banner (light and dark) in the same layout as the other family repos.

python3 assets/build_banner.py
"""

from pathlib import Path

HERE = Path(__file__).parent
FONT = "Geist, Inter, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
ARC = "M 35.91 139.73 A 81 81 0 1 1 188.09 139.73"  # same mark as assets/famiglia/parliamentrag-*.svg

THEMES = {
    "light": dict(bg="#F7F8F5", panel="#FFFFFF", ink="#14201C", ink2="#5E6B66", line="#E4E8E4", brand="#2D5F8F", soft="#EEF3F8", bar="#DCE1DE"),
    "dark": dict(bg="#0F1714", panel="#16201C", ink="#ECF0EC", ink2="#A9B5B0", line="#26302C", brand="#6E9BC8", soft="#1A2733", bar="#2E3A35"),
}

ROWS = [("FdI", 236, "1"), ("PD", 200, "2"), ("Lega", 248, "3"), ("M5S", 184, "4"), ("AVS", 222, "5")]


def mark(x, y, height, c):
    s = height / 166
    return (f'<g transform="translate({x} {y}) scale({s:.4f}) translate(0 -8)">'
            f'<path d="{ARC}" fill="none" stroke="{c["ink"]}" stroke-width="32" stroke-linecap="round"/>'
            f'<circle cx="112" cy="146" r="22" fill="{c["brand"]}"/></g>')


def banner(c):
    W, H = 1280, 440
    cx, cy = 760, 92
    rows = []
    for i, (side, width, n) in enumerate(ROWS):
        y = cy + 104 + i * 22
        rows.append(f'<text x="{cx + 28}" y="{y + 6}" font-family="{FONT}" font-size="14" fill="{c["ink2"]}">{side}</text>'
                    f'<rect x="{cx + 88}" y="{y - 4}" width="{width}" height="8" rx="5" fill="{c["bar"]}"/>'
                    f'<rect x="{cx + 100 + width}" y="{y - 9}" width="22" height="18" rx="5" fill="{c["soft"]}"/>'
                    f'<text x="{cx + 111 + width}" y="{y + 4}" text-anchor="middle" font-family="{FONT}" font-size="13" font-weight="600" fill="{c["brand"]}">{n}</text>')
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="ParliamentRAG: balanced, verifiable answers on Italian parliamentary debate.">
<rect width="{W}" height="{H}" rx="28" fill="{c["bg"]}"/>
{mark(70, 126, 76, c)}
<text x="186" y="186" font-family="{FONT}" font-size="64" font-weight="700" letter-spacing="-2.4" fill="{c["ink"]}">ParliamentRAG</text>
<text x="70" y="290" font-family="{FONT}" font-size="27" font-weight="500" letter-spacing="-0.4" fill="{c["ink"]}">Balanced answers on Italian parliamentary</text>
<text x="70" y="326" font-family="{FONT}" font-size="27" font-weight="500" letter-spacing="-0.4" fill="{c["ink"]}">debate, every quote checked at the source.</text>
<text x="70" y="378" font-family="{FONT}" font-size="19" fill="{c["ink2"]}">Research project · ISWC 2026</text>
<rect x="{cx}" y="{cy}" width="456" height="256" rx="20" fill="{c["panel"]}" stroke="{c["line"]}" stroke-width="2"/>
<rect x="{cx + 120}" y="{cy + 28}" width="312" height="48" rx="24" fill="{c["soft"]}"/>
<text x="{cx + 140}" y="{cy + 58}" font-family="{FONT}" font-size="17" fill="{c["ink"]}">What do the groups say on wages?</text>
{"".join(rows)}
<line x1="{cx + 28}" y1="{cy + 214}" x2="{cx + 428}" y2="{cy + 214}" stroke="{c["line"]}" stroke-width="2"/>
<text x="{cx + 28}" y="{cy + 240}" font-family="{FONT}" font-size="15" fill="{c["ink2"]}">Every group, verbatim quotes · camera.it ↗</text>
</svg>
'''


for name, c in THEMES.items():
    (HERE / f"banner-{name}.svg").write_text(banner(c))
