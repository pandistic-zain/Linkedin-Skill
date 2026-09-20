#!/usr/bin/env python3
"""Generate the branded illustration for the latest draft and print its URL.
Publishes nothing.

  python make_image.py           # editorial illustration from the IMAGE: brief
  python make_image.py --card    # typeset quote-card of the hook line
  python make_image.py "custom brief here"
"""
import importlib.util, os, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

spec = importlib.util.spec_from_file_location("rd", ROOT / "automation" / "run_daily.py")
rd = importlib.util.module_from_spec(spec); spec.loader.exec_module(rd)

drafts = sorted((ROOT / "drafts").glob("*.md"), key=lambda p: p.stat().st_mtime)
if not drafts:
    sys.exit("No drafts found.")
raw = drafts[-1].read_text(encoding="utf-8")
body = raw.split("\n---", 1)[0]
body = "\n".join(l for l in body.splitlines() if not l.startswith("# Draft")).strip()
note = raw.split("\n---", 1)[1] if "\n---" in raw else ""
hook = body.splitlines()[0]

custom = [a for a in sys.argv[1:] if not a.startswith("--")]

if "--card" in sys.argv:
    from lib import quote_card
    img = quote_card(hook, handle="webbyzain.online", style="brand")
else:
    brief = custom[0] if custom else (rd._image_brief(note) or hook)
    print(f"brief: {brief}\n")
    from lib import illustrate
    img = illustrate(rd.BRAND_STYLE + brief, kind="wide",
                         model=os.getenv("IMAGE_MODEL", "gpt-5-image"),
                         resolution=os.getenv("IMAGE_RESOLUTION", "2K"),
                         overlay={"text": "webbyzain.online",
                                  "position": "bottom-right",
                                  "opacity": 0.55, "color": "#F7F7F3"})

print(f"URL:  {img['url']}")
print(f"cost: {img.get('cost')}")
