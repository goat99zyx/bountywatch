"""Turn a day's changes into a personal email (HTML + text) and a JSON feed."""
import html
import json
from collections import OrderedDict

from .diff import TYPES, order

SECTION = OrderedDict([
    ("alert", ("Check before you submit", "Pauses, removals and lost bounties on programs you watch.")),
    ("opportunity", ("New for you", "New scope, bounties and higher rewards on programs you watch.")),
    ("info", ("Other updates", "Policy and disclosure changes.")),
])
PER_PROGRAM_LIMIT = 8
GLOBAL_LIMIT = 15
COLORS = {"alert": "#C2352B", "opportunity": "#1F8A4C", "info": "#5B6275"}


def _norm(s):
    return (s or "").strip().lower()


def watches(sub, change, programs):
    """Does this subscriber watch the program behind this change?"""
    w = sub.get("watch", {})
    plats = {_norm(p) for p in w.get("platforms", [])}
    if plats and _norm(change["platform"]) not in plats and change["platform"] != "security.txt":
        return False
    paid = programs.get(change["pkey"], {}).get("offers_bounties", change["detail"].get("offers_bounties"))
    if w.get("bounty_only") and paid is False and change["type"] != "bounty_changed":
        return False
    if w.get("all"):
        return True
    key, name = _norm(change["pkey"]), _norm(change["program"])
    handle = key.split(":", 1)[-1]
    for pat in w.get("programs", []):
        p = _norm(pat)
        # Exact program key ("h1:github") or handle ("github"), or part of the name (4+ characters).
        if p and (p == key or p == handle or p == name or (len(p) >= 4 and p in name)):
            return True
    for dom in w.get("domains", []):
        d = _norm(dom).lstrip("*.")
        if d and (d in _norm(change["detail"].get("asset", "")) or d == _norm(change["detail"].get("domain", ""))):
            return True
    return False


def _group(changes):
    g = OrderedDict()
    for c in changes:
        g.setdefault((c["pkey"], c["program"], c["platform"], c.get("url")), []).append(c)
    return g


def build(sub, changes, programs, day_label, global_new=None, days_left=None, renew_url=None):
    """Return dict(subject, html, text, json, counts) for one subscriber, or None if nothing to say."""
    mine = order([c for c in changes if watches(sub, c, programs)])
    global_new = global_new if global_new is not None else [
        c for c in changes if c["type"] in ("program_added", "bounty_changed") and c["bucket"] == "opportunity"
        and c["detail"].get("offers_bounties", programs.get(c["pkey"], {}).get("offers_bounties"))]
    counts = {b: sum(1 for c in mine if c["bucket"] == b) for b in SECTION}
    if not mine and not global_new and not sub.get("send_empty", True):
        return None

    n_prog = len({c["pkey"] for c in mine})
    if counts["alert"]:
        subject = f"BountyWatch {day_label}: {counts['alert']} to check before you submit"
    elif mine:
        subject = f"BountyWatch {day_label}: {len(mine)} change{'s' if len(mine) != 1 else ''} on programs you watch"
    else:
        subject = f"BountyWatch {day_label}: no changes on your watchlist"

    renew = None
    if days_left is not None and days_left <= 3:
        when = "today" if days_left == 0 else f"in {days_left} day{'s' if days_left != 1 else ''}"
        renew = f"Your 30-day pass ends {when}. Renew to keep these emails coming" + (f": {renew_url}" if renew_url and renew_url != "#" else ".")

    # ---------- text ----------
    T = [f"BountyWatch · {day_label}", ""]
    if renew:
        T += [renew, ""]
    T.append(f"{len(mine)} change(s) across {n_prog} program(s) you watch." if mine else
             "Nothing changed on the programs you watch since yesterday.")
    for bucket, (title, _) in SECTION.items():
        items = [c for c in mine if c["bucket"] == bucket]
        if not items:
            continue
        T += ["", title.upper(), "-" * len(title)]
        for (pk, pname, plat, url), cs in _group(items).items():
            T.append(f"\n{pname} ({plat}) {url or ''}".rstrip())
            for c in cs[:PER_PROGRAM_LIMIT]:
                T.append(f"  • {c['summary']}")
            if len(cs) > PER_PROGRAM_LIMIT:
                T.append(f"  • …and {len(cs) - PER_PROGRAM_LIMIT} more")
    if global_new:
        T += ["", "NEW BOUNTY PROGRAMS ON ALL PLATFORMS", "------------------------------------"]
        for c in global_new[:GLOBAL_LIMIT]:
            T.append(f"  • {c['program']} ({c['platform']}) {c.get('url') or ''} — {c['summary']}")
    T += ["", "Detected from public program listings. Always confirm scope on the platform before testing.",
          "Change your watchlist: reply to this email."]
    text = "\n".join(T)

    # ---------- html ----------
    e = html.escape
    H = ['<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#141A2E;'
         'max-width:640px;margin:0 auto;padding:16px">',
         '<div style="font-size:13px;color:#5B6275;letter-spacing:.04em;text-transform:uppercase;font-weight:700">'
         f'BountyWatch · {e(day_label)}</div>',
         '<h1 style="font-size:22px;margin:6px 0 4px">' +
         (e(f"{len(mine)} change{'s' if len(mine) != 1 else ''} across {n_prog} program{'s' if n_prog != 1 else ''} you watch")
          if mine else "No changes on your watchlist") + "</h1>"]
    if renew:
        H.append('<p style="background:#FCF0DF;border-radius:8px;padding:8px 12px;font-size:14px">' + e(renew) + "</p>")
    chips = " ".join(
        f'<span style="display:inline-block;border-radius:999px;padding:2px 10px;font-size:12px;font-weight:700;'
        f'color:{COLORS[b]};background:#F3F1EC;margin-right:4px">{counts[b]} {SECTION[b][0].lower()}</span>'
        for b in SECTION if counts[b])
    if chips:
        H.append(f'<p style="margin:6px 0 14px">{chips}</p>')
    for bucket, (title, sub_title) in SECTION.items():
        items = [c for c in mine if c["bucket"] == bucket]
        if not items:
            continue
        H.append(f'<h2 style="font-size:16px;margin:22px 0 2px;color:{COLORS[bucket]}">{e(title)}</h2>'
                 f'<div style="font-size:13px;color:#5B6275;margin-bottom:8px">{e(sub_title)}</div>')
        for (pk, pname, plat, url), cs in _group(items).items():
            name = f'<a href="{e(url)}" style="color:#141A2E">{e(pname)}</a>' if url else e(pname)
            H.append('<div style="border:1px solid #E2DED5;border-radius:10px;padding:10px 14px;margin:8px 0">'
                     f'<div style="font-weight:700">{name} <span style="font-weight:400;color:#5B6275;font-size:13px">'
                     f'{e(plat)}</span></div><ul style="margin:6px 0 0;padding-left:18px;font-size:14px">')
            for c in cs[:PER_PROGRAM_LIMIT]:
                H.append(f'<li style="margin:3px 0">{e(c["summary"])}</li>')
            if len(cs) > PER_PROGRAM_LIMIT:
                H.append(f'<li style="margin:3px 0;color:#5B6275">…and {len(cs) - PER_PROGRAM_LIMIT} more</li>')
            H.append("</ul></div>")
    if global_new:
        H.append('<h2 style="font-size:16px;margin:24px 0 6px">New bounty programs on all platforms</h2>'
                 '<ul style="padding-left:18px;font-size:14px">')
        for c in global_new[:GLOBAL_LIMIT]:
            link = f'<a href="{e(c["url"])}">{e(c["program"])}</a>' if c.get("url") else e(c["program"])
            H.append(f'<li style="margin:3px 0">{link} <span style="color:#5B6275">({e(c["platform"])})</span> — '
                     f'{e(c["summary"])}</li>')
        if len(global_new) > GLOBAL_LIMIT:
            H.append(f'<li style="color:#5B6275">…and {len(global_new) - GLOBAL_LIMIT} more</li>')
        H.append("</ul>")
    H.append('<p style="font-size:12px;color:#5B6275;margin-top:26px;border-top:1px solid #E2DED5;padding-top:10px">'
             "Detected by comparing yesterday's and today's public program listings on HackerOne, Bugcrowd, "
             "Intigriti and YesWeHack. Always confirm scope on the platform before testing. "
             "To change your watchlist, reply to this email.</p></div>")
    payload = {"date": day_label, "changes": mine, "new_bounty_programs": global_new}
    return {"subject": subject, "html": "\n".join(H), "text": text,
            "json": json.dumps(payload, indent=1, ensure_ascii=False), "counts": counts, "n": len(mine)}


def type_counts(changes):
    out = OrderedDict((t, 0) for t in TYPES)
    for c in changes:
        out[c["type"]] += 1
    return out
