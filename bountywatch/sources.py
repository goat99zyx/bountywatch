"""Load public bug bounty program data and turn it into one common shape.

Data comes from arkadiyt/bounty-targets-data (MIT License), which republishes the
public program directories of HackerOne, Bugcrowd, Intigriti and YesWeHack every
30 minutes. We read that dataset instead of crawling the platforms ourselves.
"""
import json
import subprocess
import urllib.request
from pathlib import Path

RAW = "https://raw.githubusercontent.com/arkadiyt/bounty-targets-data/main/data/{}_data.json"
PLATFORMS = ("hackerone", "bugcrowd", "intigriti", "yeswehack")
UA = "BountyWatch/1.0 (daily change digest; +https://github.com/goat99zyx)"


def _fetch(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def load_raw(source):
    """source: 'remote', a directory holding *_data.json, or 'git:<repo_dir>@<commit>'."""
    out = {}
    for p in PLATFORMS:
        if source == "remote":
            out[p] = _fetch(RAW.format(p))
        elif source.startswith("git:"):
            repo, commit = source[4:].split("@", 1)
            blob = subprocess.run(["git", "-C", repo, "show", f"{commit}:data/{p}_data.json"],
                                  check=True, capture_output=True).stdout
            out[p] = json.loads(blob)
        else:
            out[p] = json.loads((Path(source) / f"{p}_data.json").read_text(encoding="utf-8"))
    return out


def _s(v):
    return (v or "").strip() if isinstance(v, str) else v


def _money(d):
    if isinstance(d, dict):
        v = d.get("value")
        return (float(v) if v not in (None, "") else None), d.get("currency")
    if d in (None, ""):
        return None, None
    try:
        return float(d), None
    except (TypeError, ValueError):
        return None, None


def _asset(akey, atype, in_scope, bounty=None, submit=None, severity=None, tier=None):
    return {"akey": akey, "type": (atype or "").upper() or "OTHER", "in_scope": bool(in_scope),
            "bounty": bounty, "submit": submit, "severity": severity, "tier": tier}


def normalize(raw):
    """Return {program_key: program_dict}. Assets are keyed by (asset_key, in_scope)."""
    progs = {}

    for p in raw.get("hackerone", []):
        key = "h1:" + p["handle"]
        assets = []
        for side, flag in (("in_scope", True), ("out_of_scope", False)):
            for a in p.get("targets", {}).get(side, []) or []:
                assets.append(_asset(_s(a.get("asset_identifier")), a.get("asset_type"), flag,
                                     a.get("eligible_for_bounty"), a.get("eligible_for_submission"),
                                     a.get("max_severity")))
        progs[key] = {"key": key, "platform": "HackerOne", "name": _s(p.get("name")) or p["handle"],
                      "url": p.get("url"), "website": p.get("website"),
                      "state": p.get("submission_state") or "open",
                      "offers_bounties": bool(p.get("offers_bounties")),
                      "min_reward": None, "max_reward": None, "currency": None, "assets": assets}

    for p in raw.get("bugcrowd", []):
        url = p.get("url") or ""
        key = "bc:" + url.rstrip("/").split("/")[-1]
        assets = []
        for side, flag in (("in_scope", True), ("out_of_scope", False)):
            for a in p.get("targets", {}).get(side, []) or []:
                assets.append(_asset(_s(a.get("target") or a.get("uri") or a.get("name")), a.get("type"), flag))
        mx, _ = _money(p.get("max_payout"))
        progs[key] = {"key": key, "platform": "Bugcrowd", "name": _s(p.get("name")), "url": url,
                      "website": None, "state": "open", "offers_bounties": bool(mx and mx > 0),
                      "min_reward": None, "max_reward": mx, "currency": "USD", "assets": assets}

    for p in raw.get("intigriti", []):
        key = "it:{}/{}".format(p.get("company_handle"), p.get("handle"))
        assets = []
        for side, flag in (("in_scope", True), ("out_of_scope", False)):
            for a in p.get("targets", {}).get(side, []) or []:
                tier = a.get("impact")
                bounty = None if tier is None else (tier not in ("No Bounty", "Out Of Scope", "Out of scope"))
                assets.append(_asset(_s(a.get("endpoint")), a.get("type"), flag, bounty, None, None, tier))
        mn, cur = _money(p.get("min_bounty"))
        mx, cur2 = _money(p.get("max_bounty"))
        progs[key] = {"key": key, "platform": "Intigriti", "name": _s(p.get("name")), "url": p.get("url"),
                      "website": None, "state": p.get("status") or "open",
                      "offers_bounties": bool(mx and mx > 0), "min_reward": mn, "max_reward": mx,
                      "currency": cur or cur2, "assets": assets}

    for p in raw.get("yeswehack", []):
        key = "ywh:" + str(p.get("id"))
        assets = []
        for side, flag in (("in_scope", True), ("out_of_scope", False)):
            for a in p.get("targets", {}).get(side, []) or []:
                assets.append(_asset(_s(a.get("target")), a.get("type"), flag))
        mn, _ = _money(p.get("min_bounty"))
        mx, _ = _money(p.get("max_bounty"))
        progs[key] = {"key": key, "platform": "YesWeHack", "name": _s(p.get("name")),
                      "url": "https://yeswehack.com/programs/" + str(p.get("id")), "website": None,
                      "state": "disabled" if p.get("disabled") else "open",
                      "offers_bounties": bool(mx and mx > 0), "min_reward": mn, "max_reward": mx,
                      "currency": "EUR", "assets": assets}

    # Collapse exact duplicate assets inside a program (the source occasionally repeats rows).
    for pr in progs.values():
        seen, uniq = set(), []
        for a in pr["assets"]:
            k = (a["akey"], a["in_scope"])
            if a["akey"] and k not in seen:
                seen.add(k)
                uniq.append(a)
        pr["assets"] = uniq
    return progs
