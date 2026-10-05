"""Writes the iOS launch images (apple-touch-startup-image) into public/splash.

Each image is a screenshot of the page's own launch screen frozen on its first
frame (?launch=still), so the OS splash and the first painted frame match pixel
for pixel. The device list mirrors SPLASH_DEVICES in src/app/layout.tsx.

Needs a running build and Python Playwright with Chromium:
    npm run build && PORT=3031 npm start
    python scripts/generate_splash.py --base http://localhost:3031
"""

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

DEVICES = [  # CSS width, CSS height, device pixel ratio
    (440, 956, 3),  # 16 Pro Max, 17 Pro Max
    (430, 932, 3),  # 14 Pro Max, 15 Plus / Pro Max, 16 Plus
    (428, 926, 3),  # 12-13 Pro Max, 14 Plus
    (420, 912, 3),  # Air
    (414, 896, 3),  # XS Max, 11 Pro Max
    (414, 896, 2),  # XR, 11
    (402, 874, 3),  # 16 Pro, 17, 17 Pro
    (393, 852, 3),  # 14 Pro, 15, 15 Pro, 16
    (390, 844, 3),  # 12, 13, 14, 12-13 Pro
    (375, 812, 3),  # X, XS, 11 Pro, 12-13 mini
    (375, 667, 2),  # SE 2nd and 3rd gen, 8
]
SCHEMES = ("light", "dark")
OUT = Path(__file__).resolve().parent.parent / "public" / "splash"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:3031")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for scheme in SCHEMES:
            for w, h, dpr in DEVICES:
                ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=dpr, color_scheme=scheme)
                # The launch screen is HTML and CSS only: without the app's scripts nothing else moves.
                ctx.route("**/*.{js,mjs}", lambda route: route.abort())
                page = ctx.new_page()
                page.goto(f"{args.base}/?launch=still", wait_until="domcontentloaded")
                page.locator(".launch").wait_for(state="visible")
                page.screenshot(path=str(OUT / f"apple-splash-{w * dpr}x{h * dpr}-{scheme}.png"))
                ctx.close()
        browser.close()
    print(f"wrote {len(DEVICES) * len(SCHEMES)} launch images to {OUT}")


if __name__ == "__main__":
    main()
