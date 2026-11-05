"""Compare two snapshots and name what changed.

Ten change types. Each change lands in a bucket:
  "alert"       could waste or invalidate a hunter's work (pause, removal, bounty dropped)
  "opportunity" new places to look or more money
  "info"        worth knowing, not urgent
"""
from datetime import datetime, timezone

from .securitytxt import expires_at

TYPES = {
    "program_added": "New program",
    "program_removed": "Program no longer listed",
    "state_changed": "Submission status changed",
    "bounty_changed": "Bounties turned on or off",
    "reward_changed": "Reward range changed",
    "asset_added": "Asset added to scope",
    "asset_removed": "Asset removed from scope",
    "eligibility_changed": "Asset eligibility changed",
    "severity_changed": "Severity cap changed",
    "securitytxt_changed": "security.txt changed",
}

SEV_RANK = {None: -1, "none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def _money(v, cur):
    if v is None:
        return "none"
    return f"{v:,.0f} {cur or ''}".strip()


def _c(t, bucket, prog, summary, **detail):
    detail.setdefault("url", prog.get("url"))
    detail.setdefault("offers_bounties", prog.get("offers_bounties"))
    return {"type": t, "bucket": bucket, "pkey": prog["key"], "platform": prog["platform"],
            "program": prog["name"], "url": prog.get("url"), "summary": summary, "detail": detail}


def _asset_label(a):
    return f"{a['akey']} ({a['type'].lower().replace('_', ' ')})"


PLATFORM_DROP_GUARD = 0.2  # if a platform loses >20% of its programs at once, assume a data glitch


def diff_programs(old, new):
    out = []
    suspect = set()
    for plat in {p["platform"] for p in old.values()}:
        before = sum(1 for p in old.values() if p["platform"] == plat)
        after = sum(1 for p in new.values() if p["platform"] == plat)
        if before and before - after >= 5 and (before - after) / before > PLATFORM_DROP_GUARD:
            suspect.add(plat)
    for k in sorted(set(new) - set(old)):
        p = new[k]
        n = sum(1 for a in p["assets"] if a["in_scope"])
        money = "pays bounties" if p["offers_bounties"] else "no bounties (VDP)"
        out.append(_c("program_added", "opportunity", p,
                      f"New public program: {n} in-scope asset{'s' if n != 1 else ''}, {money}.",
                      in_scope=n, offers_bounties=p["offers_bounties"]))
    for k in sorted(set(old) - set(new)):
        p = old[k]
        if p["platform"] in suspect:
            continue
        out.append(_c("program_removed", "alert", p,
                      "No longer listed as a public, open program. It may be paused, closed or made private. "
                      "Check before you submit.", last_state=p["state"]))
    for k in sorted(set(old) & set(new)):
        a, b = old[k], new[k]
        if (a["state"] or "") != (b["state"] or ""):
            bucket = "opportunity" if b["state"] == "open" else "alert"
            out.append(_c("state_changed", bucket, b, f"Submission status: {a['state']} → {b['state']}.",
                          before=a["state"], after=b["state"]))
        if a["offers_bounties"] != b["offers_bounties"]:
            on = b["offers_bounties"]
            out.append(_c("bounty_changed", "opportunity" if on else "alert", b,
                          "Now offers bounties." if on else "No longer offers bounties.",
                          before=a["offers_bounties"], after=on))
        if (a["max_reward"], a["min_reward"]) != (b["max_reward"], b["min_reward"]) and \
                not (a["offers_bounties"] != b["offers_bounties"] and (b["max_reward"] in (None, 0))):
            up = (b["max_reward"] or 0) > (a["max_reward"] or 0)
            rng = lambda p: (f"{_money(p['min_reward'], p['currency'])}–" if p["min_reward"] else "") + \
                _money(p["max_reward"], p["currency"])
            out.append(_c("reward_changed", "opportunity" if up else "alert", b,
                          f"Max reward {rng(a)} → {rng(b)}.", before=[a["min_reward"], a["max_reward"]],
                          after=[b["min_reward"], b["max_reward"]]))
        out.extend(_diff_assets(a, b))
    return out


def _diff_assets(pa, pb):
    out = []
    A = {(x["akey"], x["in_scope"]): x for x in pa["assets"]}
    B = {(x["akey"], x["in_scope"]): x for x in pb["assets"]}
    a_in = {k[0] for k in A if k[1]}
    b_in = {k[0] for k in B if k[1]}
    b_out = {k[0] for k in B if not k[1]}

    for akey in sorted(b_in - a_in):
        x = B[(akey, True)]
        paid = x["bounty"]
        note = " Eligible for bounty." if paid else (" Not eligible for bounty." if paid is False else "")
        sev = f" Max severity {x['severity']}." if x.get("severity") else ""
        tier = f" Reward tier: {x['tier']}." if x.get("tier") else ""
        out.append(_c("asset_added", "opportunity", pb, f"Added to scope: {_asset_label(x)}.{note}{sev}{tier}",
                      asset=akey, asset_type=x["type"], bounty=paid))
    for akey in sorted(a_in - b_in):
        x = A[(akey, True)]
        moved = akey in b_out
        out.append(_c("asset_removed", "alert", pb,
                      f"{'Moved out of scope' if moved else 'Removed from scope'}: {_asset_label(x)}.",
                      asset=akey, asset_type=x["type"], moved_out_of_scope=moved))
    for akey in sorted(a_in & b_in):
        x, y = A[(akey, True)], B[(akey, True)]
        bits, bucket = [], "info"
        if x["bounty"] != y["bounty"] and None not in (x["bounty"], y["bounty"]):
            bits.append("now eligible for bounty" if y["bounty"] else "no longer eligible for bounty")
            bucket = "opportunity" if y["bounty"] else "alert"
        if x["submit"] != y["submit"] and None not in (x["submit"], y["submit"]):
            bits.append("accepts submissions again" if y["submit"] else "no longer accepts submissions")
            bucket = "alert" if not y["submit"] else ("opportunity" if bucket == "info" else bucket)
        if (x.get("tier") or None) != (y.get("tier") or None):
            bits.append(f"reward tier {x.get('tier') or 'none'} → {y.get('tier') or 'none'}")
        if bits:
            out.append(_c("eligibility_changed", bucket, pb, f"{_asset_label(y)}: " + "; ".join(bits) + ".",
                          asset=akey, before={"bounty": x["bounty"], "submit": x["submit"], "tier": x.get("tier")},
                          after={"bounty": y["bounty"], "submit": y["submit"], "tier": y.get("tier")}))
        if (x.get("severity") or None) != (y.get("severity") or None):
            up = SEV_RANK.get(y.get("severity"), -1) > SEV_RANK.get(x.get("severity"), -1)
            out.append(_c("severity_changed", "opportunity" if up else "alert", pb,
                          f"{_asset_label(y)}: max severity {x.get('severity') or 'none'} → {y.get('severity') or 'none'}.",
                          asset=akey, before=x.get("severity"), after=y.get("severity")))
    return out


def diff_securitytxt(old, new, owners=None, now=None, since=None):
    """old/new: {domain: fetch result}. owners: {domain: program dict} for labelling.
    since: time of the previous snapshot, used to spot files that expired in between."""
    now = now or datetime.now(timezone.utc)
    owners = owners or {}
    out = []
    for d in sorted(set(old) & set(new)):
        a, b = old[d], new[d]
        if b["status"] == "error" or a["status"] == "error":
            continue  # network hiccups are not changes
        prog = owners.get(d) or {"key": "domain:" + d, "platform": "security.txt", "name": d, "url": b.get("url")}
        if a["status"] != b["status"]:
            if b["status"] == "ok":
                out.append(_c("securitytxt_changed", "info", prog, f"{d} published a security.txt.", domain=d))
            else:
                out.append(_c("securitytxt_changed", "info", prog, f"{d} no longer serves a security.txt.", domain=d))
            continue
        if b["status"] != "ok" or a["sha"] == b["sha"]:
            continue
        bits = []
        for f in ("expires", "policy", "contact", "encryption", "acknowledgments"):
            if a["fields"].get(f) != b["fields"].get(f):
                bits.append(f"{f.capitalize()}: {', '.join(a['fields'].get(f, [])) or 'none'} → "
                            f"{', '.join(b['fields'].get(f, [])) or 'none'}")
        if not bits:
            bits.append("other fields changed")
        out.append(_c("securitytxt_changed", "info", prog, f"{d} security.txt — " + "; ".join(bits) + ".", domain=d))
    # A file that expired since the last run is worth a line even when its text didn't change.
    for d in sorted(set(old) & set(new)):
        a, b = old[d], new[d]
        if a["status"] == b["status"] == "ok" and a["sha"] == b["sha"]:
            eb = expires_at(b["fields"])
            if eb and since is not None and since <= eb < now:
                prog = owners.get(d) or {"key": "domain:" + d, "platform": "security.txt", "name": d, "url": b.get("url")}
                out.append(_c("securitytxt_changed", "info", prog,
                              f"{d} security.txt expired on {eb.date().isoformat()} (RFC 9116 says to treat it as stale).",
                              domain=d, expired=True))
    return out


def order(changes):
    rank = {"alert": 0, "opportunity": 1, "info": 2}
    return sorted(changes, key=lambda c: (rank[c["bucket"]], c["program"].lower(), c["type"], c["summary"]))
