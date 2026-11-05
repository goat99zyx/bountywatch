"""BountyWatch command line.

  python -m bountywatch run          collect -> snapshot -> diff -> emails -> public page (the daily job)
  python -m bountywatch snapshot     collect and store one snapshot
  python -m bountywatch diff         compare the two latest snapshots and print a summary
  python -m bountywatch report       build emails for the latest diff (writes previews, optionally sends)
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import diff as D
from . import report as R
from . import securitytxt, site, sources
from .store import Store


def _domains(programs, extra_file):
    """Domains to check for security.txt: HackerOne program websites plus an optional list."""
    owners = {}
    for p in programs.values():
        w = (p.get("website") or "").strip()
        if not w:
            continue
        host = w.split("://", 1)[-1].split("/")[0].split(":")[0].lower()
        if host.startswith("www."):
            host = host[4:]
        if "." in host:
            owners.setdefault(host, p)
    if extra_file and Path(extra_file).exists():
        for line in Path(extra_file).read_text().splitlines():
            line = line.split("#")[0].strip().lower()
            if line:
                owners.setdefault(line, None)
    return owners


def cmd_snapshot(a, st):
    raw = sources.load_raw(a.source)
    progs = sources.normalize(raw)
    sec = None
    if a.securitytxt:
        owners = _domains(progs, a.domains)
        sec = securitytxt.fetch_all(list(owners), workers=a.workers)
    sid = st.save_snapshot(progs, sec, source=a.source, label=a.label or "", taken_at=a.taken_at)
    n_assets = sum(len(p["assets"]) for p in progs.values())
    print(f"snapshot {sid}: {len(progs)} programs, {n_assets} assets"
          + (f", {sum(1 for r in sec.values() if r['status'] == 'ok')}/{len(sec)} security.txt files" if sec else ""))
    return sid


def cmd_diff(a, st):
    ids = st.snapshot_ids()
    if len(ids) < 2:
        print("need two snapshots to compare")
        return None
    prev, cur = ids[-2], ids[-1]
    old_p, old_s = st.load(prev)
    new_p, new_s = st.load(cur)
    since = datetime.fromisoformat(st.snapshot_info(prev)["taken_at"])
    now = datetime.fromisoformat(st.snapshot_info(cur)["taken_at"])
    owners = {}
    for p in new_p.values():
        w = (p.get("website") or "").split("://", 1)[-1].split("/")[0].lower()
        owners.setdefault(w[4:] if w.startswith("www.") else w, p)
    changes = D.order(D.diff_programs(old_p, new_p) + D.diff_securitytxt(old_s, new_s, owners, now=now, since=since))
    st.save_changes(cur, prev, changes)
    counts = R.type_counts(changes)
    print(f"{len(changes)} changes between snapshot {prev} and {cur}:")
    for t, n in counts.items():
        print(f"  {D.TYPES[t]:<28} {n}")
    return changes, new_p


def _load_changes(st):
    ids = st.snapshot_ids()
    cur = ids[-1]
    rows = st.db.execute("SELECT type,bucket,pkey,platform,program,summary,detail FROM changes "
                         "WHERE snapshot_id=? ORDER BY seq", (cur,)).fetchall()
    progs, _ = st.load(cur)
    changes = [{"type": r[0], "bucket": r[1], "pkey": r[2], "platform": r[3], "program": r[4],
                "summary": r[5], "detail": json.loads(r[6]),
                "url": json.loads(r[6]).get("url") or progs.get(r[2], {}).get("url")} for r in rows]
    return changes, progs, st.snapshot_info(cur)


def cmd_report(a, st):
    changes, progs, info = _load_changes(st)
    day = a.day or datetime.fromisoformat(info["taken_at"]).strftime("%a %d %b %Y")
    subs = []
    if os.environ.get("SUBSCRIBERS_KEY") and Path("subscribers").exists():
        from . import subscribers as SB
        subs += SB.load_all(os.environ["SUBSCRIBERS_KEY"])
    if os.environ.get("SUBSCRIBERS_JSON"):
        subs += json.loads(os.environ["SUBSCRIBERS_JSON"])
    have_real = bool(subs)
    if not subs:
        subs = json.loads(Path(a.subscribers).read_text())
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    sent = 0
    if a.send and not (os.environ.get("SMTP_HOST") and have_real):
        print("No SMTP settings or no real subscribers: writing previews only, nothing sent")
        a.send = False
    for i, sub in enumerate(subs):
        if not sub.get("active", True):
            continue
        left = None
        if sub.get("expires"):
            left = (datetime.fromisoformat(sub["expires"]).date() - datetime.now(timezone.utc).date()).days
            if left < 0:
                continue  # pass ended
        r = R.build(sub, changes, progs, day, days_left=left, renew_url=a.signup_url)
        if not r:
            continue
        stem = out / f"email-{i + 1}"
        stem.with_suffix(".html").write_text(r["html"], encoding="utf-8")
        stem.with_suffix(".txt").write_text(f"Subject: {r['subject']}\n\n{r['text']}", encoding="utf-8")
        if a.send:
            from .mailer import send
            att = (f"bountywatch-{datetime.now(timezone.utc).date()}.json", r["json"]) if sub.get("plan") == "pro" else None
            try:
                send(sub["email"], r["subject"], r["html"], r["text"], att)
                sent += 1
            except Exception as exc:  # one bad address must not stop the rest
                print(f"subscriber {i + 1}: send failed ({type(exc).__name__})")
    print(f"{len(subs)} subscribers, previews in {out}" + (f", {sent} emails sent" if a.send else " (not sent)"))
    if a.site:
        site.write(a.site, changes, progs, day, a.signup_url, a.site_url)
        print(f"public page written to {a.site}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bountywatch")
    ap.add_argument("command", choices=["run", "snapshot", "diff", "report", "add-subscriber"])
    ap.add_argument("--email")
    ap.add_argument("--programs", default="", help="comma-separated handles or names")
    ap.add_argument("--watch-domains", dest="watch_domains", default="")
    ap.add_argument("--all", dest="all_programs", action="store_true")
    ap.add_argument("--bounty-only", dest="bounty_only", action="store_true")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--plan", default="standard")
    ap.add_argument("--start", default=None, help="pass start date YYYY-MM-DD (default today)")
    ap.add_argument("--db", default="data/bountywatch.sqlite")
    ap.add_argument("--source", default="remote", help="remote | <dir with *_data.json> | git:<repo>@<commit>")
    ap.add_argument("--label", default="")
    ap.add_argument("--taken-at", dest="taken_at", default=None, help="ISO time for backfilled snapshots")
    ap.add_argument("--securitytxt", action="store_true", help="also fetch security.txt files")
    ap.add_argument("--domains", default="config/domains.txt")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--subscribers", default="config/subscribers.json")
    ap.add_argument("--out", default="out")
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--site", default=None, help="write the public page to this folder")
    ap.add_argument("--site-url", dest="site_url", default="https://example.github.io/bountywatch/")
    ap.add_argument("--signup-url", dest="signup_url", default="#")
    ap.add_argument("--day", default=None)
    ap.add_argument("--keep", type=int, default=3, help="snapshots to keep (each is ~8 MB)")
    a = ap.parse_args(argv)
    if a.command == "add-subscriber":
        from datetime import date
        from . import subscribers as SB
        rec = SB.make_record(a.email, a.programs.split(","), a.watch_domains.split(","), a.all_programs,
                             a.bounty_only, a.days, a.plan, date.fromisoformat(a.start) if a.start else None)
        path = SB.save(rec)
        print(f"saved {path} (pass ends {rec['expires']})")
        return 0
    Path(a.db).parent.mkdir(parents=True, exist_ok=True)
    st = Store(a.db)
    if a.command == "snapshot":
        cmd_snapshot(a, st)
    elif a.command == "diff":
        cmd_diff(a, st)
    elif a.command == "report":
        cmd_report(a, st)
    else:
        cmd_snapshot(a, st)
        if cmd_diff(a, st) is not None:
            cmd_report(a, st)
        st.prune(a.keep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
