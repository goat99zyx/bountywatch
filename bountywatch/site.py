"""Public free page: today's headline numbers, new bounty programs and programs that dropped off.

This is the free tier and the marketing page. Watchlists and full asset-level detail stay in the paid email.
"""
import html
import json
from datetime import datetime, timezone
from pathlib import Path

from .diff import TYPES
from .report import type_counts

e = html.escape


def render(changes, programs, day_label, signup_url, history=None):
    counts = type_counts(changes)
    new_bounty = [c for c in changes if c["type"] == "program_added" and programs.get(c["pkey"], {}).get("offers_bounties")]
    gone = [c for c in changes if c["type"] == "program_removed"]
    n_prog = len({c["pkey"] for c in changes})
    rows = "".join(f"<tr><td>{e(TYPES[t])}</td><td style='text-align:right'>{n:,}</td></tr>" for t, n in counts.items())
    li = lambda cs: "".join(
        f"<li><a href='{e(c['url'] or '#')}'>{e(c['program'])}</a> <span class='m'>{e(c['platform'])}</span></li>"
        for c in cs) or "<li class='m'>None today.</li>"
    hist = ""
    if history:
        hist = "<h2>Last days</h2><table>" + "".join(
            f"<tr><td>{e(d)}</td><td style='text-align:right'>{n:,} changes</td></tr>" for d, n in history) + "</table>"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BountyWatch: daily bug bounty program changes</title>
<meta name="description" content="Every day BountyWatch compares the public programs on HackerOne, Bugcrowd, Intigriti and YesWeHack and emails you what changed on the ones you hunt: pauses, removed scope, new assets and bounty changes.">
<link rel="alternate" type="application/rss+xml" title="BountyWatch daily" href="feed.xml">
<style>
:root{{--ink:#E8EAF2;--muted:#9AA3B8;--bg:#0E1220;--card:#161B2E;--line:#262D45;--acc:#5B8CFF;--red:#FF6B5E;--grn:#3DDC97}}
*{{box-sizing:border-box}}html,body{{margin:0}}body{{background:var(--bg);color:var(--ink);font:16px/1.55 -apple-system,Segoe UI,Inter,Roboto,Helvetica,Arial,sans-serif}}
a{{color:var(--acc)}}.w{{max-width:920px;margin:0 auto;padding:28px 16px 60px}}
h1{{font-size:clamp(28px,5vw,44px);line-height:1.08;margin:0 0 10px;letter-spacing:-.02em}}
.lead{{color:var(--muted);font-size:18px;max-width:680px}}
.cta{{display:inline-block;background:var(--acc);color:#fff;text-decoration:none;font-weight:800;padding:12px 18px;border-radius:12px;margin:10px 0 6px}}
.grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:22px 0}}
.k{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px}}.k b{{font-size:30px;display:block}}
.k.r b{{color:var(--red)}}.k.g b{{color:var(--grn)}}
.cols{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px}}
h2{{font-size:18px;margin:6px 0 10px}}ul{{padding-left:18px;margin:0}}li{{margin:4px 0}}.m{{color:var(--muted);font-size:13px}}
table{{width:100%;border-collapse:collapse;font-size:14px}}td{{padding:6px 0;border-bottom:1px solid var(--line)}}
footer{{color:var(--muted);font-size:13px;margin-top:30px}}
@media(max-width:720px){{.grid,.cols{{grid-template-columns:1fr}}}}
</style></head><body><div class="w">
<div class="m" style="font-weight:700;letter-spacing:.06em;text-transform:uppercase">BountyWatch · {e(day_label)}</div>
<h1>Know when the programs you hunt change.</h1>
<p class="lead">Every day BountyWatch compares the public programs on HackerOne, Bugcrowd, Intigriti and YesWeHack and emails you what changed on the ones you hunt: pauses, removed scope, new assets and bounty changes. Catch it before you spend a weekend on a target that's gone.</p>
<a class="cta" href="{e(signup_url)}">Get your daily watchlist email</a>
<div class="grid">
<div class="k"><b>{len(changes):,}</b>changes in the last 24 hours</div>
<div class="k r"><b>{len(gone):,}</b>programs dropped off the public list</div>
<div class="k g"><b>{counts['asset_added']:,}</b>assets added to scope</div>
</div>
<div class="cols">
<div class="card"><h2>New bounty programs</h2><ul>{li(new_bounty)}</ul></div>
<div class="card"><h2>No longer listed (paused, closed or private)</h2><ul>{li(gone)}</ul></div>
</div>
<div class="card" style="margin-top:16px"><h2>All changes today ({n_prog:,} programs)</h2><table>{rows}</table>
<p class="m">Which assets were added or removed, and on which programs, is in the daily email for the programs you watch.</p></div>
{('<div class="card" style="margin-top:16px">' + hist + '</div>') if hist else ''}
<footer>Data: public program listings, via the open bounty-targets-data project (MIT). Not affiliated with HackerOne, Bugcrowd, Intigriti or YesWeHack. Always confirm scope on the platform before testing. Updated {e(datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'))}.</footer>
</div></body></html>"""


def rss(entries, site_url):
    items = "".join(
        f"<item><title>{e(t)}</title><link>{e(site_url)}</link><guid isPermaLink='false'>{e(g)}</guid>"
        f"<pubDate>{e(p)}</pubDate><description>{e(d)}</description></item>" for t, g, p, d in entries)
    return (f"<?xml version='1.0' encoding='UTF-8'?><rss version='2.0'><channel><title>BountyWatch daily</title>"
            f"<link>{e(site_url)}</link><description>Daily changes to public bug bounty programs</description>{items}"
            "</channel></rss>")


def write(out_dir, changes, programs, day_label, signup_url, site_url):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    log = out / "history.json"
    hist = json.loads(log.read_text()) if log.exists() else []
    hist = [h for h in hist if h["date"] != day_label] + [{
        "date": day_label, "changes": len(changes),
        "new_bounty_programs": [c["program"] for c in changes if c["type"] == "program_added"
                                and programs.get(c["pkey"], {}).get("offers_bounties")],
        "removed": [c["program"] for c in changes if c["type"] == "program_removed"]}]
    hist = hist[-60:]
    log.write_text(json.dumps(hist, indent=1), encoding="utf-8")
    recent = [(h["date"], h["changes"]) for h in reversed(hist[-7:])]
    (out / "index.html").write_text(render(changes, programs, day_label, signup_url, recent), encoding="utf-8")
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    entries = [(f"{h['date']}: {h['changes']} changes, {len(h['new_bounty_programs'])} new bounty programs, "
                f"{len(h['removed'])} dropped off", "bw-" + h["date"], now,
                "New: " + (", ".join(h["new_bounty_programs"]) or "none") + ". Dropped off: " +
                (", ".join(h["removed"]) or "none") + ".") for h in reversed(hist[-30:])]
    (out / "feed.xml").write_text(rss(entries, site_url), encoding="utf-8")
