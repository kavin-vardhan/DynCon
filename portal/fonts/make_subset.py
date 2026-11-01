"""Build the bundled Noto Sans JP subset the portal ships with.

    py -3 portal\\fonts\\make_subset.py            # rewrites the two .woff2 files

Why a subset: the portal is a ten-foot, offline, no-CDN kiosk app (specs/portal_spec_v1.md
§1), so the font has to sit in the repo — and the full Noto Sans JP is tens of megabytes.
Every Japanese word the portal can draw lives in one file, `portal/strings.js`, so the exact
glyph set is knowable: this script reads that file, adds the whole of ASCII, all kana and
the punctuation the layout uses, and asks Google Fonts for a woff2 cut to exactly those
glyphs (the `text=` parameter of the CSS API). The result is a few kilobytes per weight.

Run it again whenever `strings.js` grows a character it has never had. Nothing at the booth
runs this; the output is committed. If a glyph ever is missing, the CSS stack in style.css
falls back to the system Japanese font rather than showing a blank box.

Licence: Noto Sans JP is under the SIL Open Font Licence 1.1. The licence text is fetched
alongside the fonts and written to OFL.txt, which must stay next to the .woff2 files.
"""
from __future__ import annotations

import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
STRINGS = HERE.parent / "strings.js"
FAMILY = "Noto Sans JP"
WEIGHTS = (400, 700)
# A browser user-agent is what makes the CSS API hand back woff2 instead of ttf.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0.0.0 Safari/537.36")
OFL_SOURCES = [
    "https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/LICENSE",
    "https://raw.githubusercontent.com/googlefonts/noto-fonts/main/OFL.txt",
    "https://openfontlicense.org/documents/OFL.txt",
]


def fetch(url: str, *, binary: bool = False) -> bytes | str:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=60) as response:
        raw = response.read()
    return raw if binary else raw.decode("utf-8")


def wanted_characters() -> str:
    """Everything the portal can draw: the strings file, ASCII, kana, punctuation."""
    text = STRINGS.read_text(encoding="utf-8")
    chars = set(text)
    chars |= {chr(c) for c in range(0x20, 0x7F)}                 # ASCII
    chars |= {chr(c) for c in range(0x3041, 0x30A0)}             # hiragana
    chars |= {chr(c) for c in range(0x30A0, 0x3100)}             # katakana
    chars |= set("、。・「」『』（）〜：％　…—–·×÷±°№")        # JP punctuation and signs
    chars |= set("0123456789")
    chars = {c for c in chars if c.isprintable() and c not in "\n\r\t"}
    return "".join(sorted(chars))


def css_for(text: str) -> str:
    weights = ";".join(str(w) for w in WEIGHTS)
    query = urllib.parse.urlencode({
        "family": f"{FAMILY}:wght@{weights}",
        "text": text,
        "display": "swap",
    })
    return fetch(f"https://fonts.googleapis.com/css2?{query}")


def main() -> int:
    text = wanted_characters()
    print(f"{len(text)} distinct characters wanted")
    css = css_for(text)
    blocks = [b for b in css.split("@font-face") if "src:" in b]
    if not blocks:
        print("the CSS API answered with no @font-face blocks:\n" + css[:400])
        return 1

    # Noto Sans JP is a variable font: the CSS API answers both weights with one and the
    # same subset file, which style.css then declares once over the 100-900 range. If that
    # ever changes, this writes one file per distinct URL and says so.
    urls: dict[str, list[str]] = {}
    for block in blocks:
        weight = re.search(r"font-weight:\s*(\d+)", block)
        url = re.search(r"url\((https://[^)]+)\)", block)
        if weight and url:
            urls.setdefault(url.group(1), []).append(weight.group(1))
    if not urls:
        print("no weight/url pair in the CSS answer")
        return 1

    for url, weights in urls.items():
        blob = fetch(url, binary=True)
        name = "NotoSansJP-subset.woff2" if len(urls) == 1 else f"NotoSansJP-{weights[0]}.woff2"
        (HERE / name).write_bytes(blob)
        print(f"wrote {name}  {len(blob) / 1024:.1f} KB  (weights {', '.join(weights)})")

    licence = HERE / "OFL.txt"
    if not licence.is_file():
        for url in OFL_SOURCES:
            try:
                licence.write_text(fetch(url), encoding="utf-8", newline="\n")
                print(f"wrote OFL.txt from {url}")
                break
            except Exception as problem:            # noqa: BLE001 - any failure, try next
                print(f"  {url}: {problem}")
        else:
            print("could not fetch the OFL text — write OFL.txt by hand before shipping")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
