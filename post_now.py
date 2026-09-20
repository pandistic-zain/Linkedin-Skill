#!/usr/bin/env python3
"""Publish the latest draft to LinkedIn via Publora, after the same guards
the daily pipeline uses.  Run from this folder:  python post_now.py
Add --dry to print what would be posted without publishing."""
import importlib.util, os, pathlib, sys
from datetime import datetime, timedelta, timezone

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
latest = drafts[-1]

body = latest.read_text(encoding="utf-8").split("\n---", 1)[0]
body = "\n".join(l for l in body.splitlines() if not l.startswith("# Draft"))
body = rd._strip_preamble(body).strip()

problem = rd._looks_like_commentary(body)
if problem:
    sys.exit(f"REFUSING: {problem}\nFix {latest.name} and retry.")

print(f"--- {latest.name}  ({len(body)} chars) ---\n{body}\n---")

if "--dry" in sys.argv:
    sys.exit("Dry run. Nothing published.")

raw = latest.read_text(encoding="utf-8")
note = raw.split("\n---", 1)[1] if "\n---" in raw else ""

media = None
if "--no-image" not in sys.argv:
    brief = rd._image_brief(note)
    if not brief:
        # older drafts have no IMAGE: line - fall back to the hook
        brief = body.splitlines()[0]
        print("no IMAGE: brief in draft, using the hook line")
    print(f"image brief: {brief[:100]}")
    if "--card" in sys.argv:
        from lib import quote_card
        img = quote_card(body.splitlines()[0], handle="webbyzain.online", style="brand")
    else:
        from lib import illustrate
        img = illustrate(rd.BRAND_STYLE + brief, kind="wide",
                         model=os.getenv("IMAGE_MODEL", "gpt-5-image"),
                         resolution=os.getenv("IMAGE_RESOLUTION", "2K"),
                         overlay={"text": "webbyzain.online",
                                  "position": "bottom-right",
                                  "opacity": 0.55, "color": "#F7F7F3"})
    media = [img["url"]]
    print(f"image: {img['url']}  cost: {img.get('cost')}")

from lib import publish
# Publora treats scheduled_time=None as a DRAFT - it never reaches LinkedIn.
# Schedule two minutes out so it actually publishes.
when = (datetime.now(timezone.utc) + timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
print(f"scheduling for {when} (UTC)")
res = publish(kind="post", draft_text=body,
              target_url="https://www.linkedin.com/post/new/",
              platforms=[os.environ["LINKEDIN_PLATFORM_ID"]],
              scheduled_time=when, media_urls=media)
print("PUBLISHED:", res)
print("\nTo cancel while still queued:")
gid = res.get("postGroupId") if isinstance(res, dict) else None
if gid:
    print(f'  python -c "import sys;sys.path.insert(0,\'.\');from lib import unpublish;print(unpublish(post_group_id=\'{gid}\'))"')
