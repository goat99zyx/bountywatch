"""Fetch and parse security.txt files (RFC 9116).

One polite GET per domain per run: /.well-known/security.txt, falling back to
/security.txt. Nothing else on the site is touched.
"""
import concurrent.futures as cf
import hashlib
import re
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timezone

UA = "BountyWatch/1.0 (reads security.txt once a day; RFC 9116)"
FIELDS = ("contact", "expires", "policy", "encryption", "acknowledgments", "preferred-languages",
          "canonical", "hiring")
MAX_BYTES = 64 * 1024


def parse(text):
    out = {}
    body = text
    # Strip a PGP clear-signature wrapper if present.
    m = re.search(r"-----BEGIN PGP SIGNED MESSAGE-----.*?\n\n(.*?)-----BEGIN PGP SIGNATURE-----", text, re.S)
    if m:
        body = m.group(1)
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip().lower()
        if k in FIELDS:
            out.setdefault(k, []).append(v.strip())
    return {k: sorted(set(v)) for k, v in out.items()}


def expires_at(fields):
    for v in fields.get("expires", []):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _get(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/plain"})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        ctype = r.headers.get("Content-Type", "")
        data = r.read(MAX_BYTES).decode("utf-8", "replace")
        return r.status, ctype, data


def fetch(domain, timeout=10):
    """Return {'domain', 'status': 'ok'|'missing'|'error', 'fields', 'sha', 'url'}."""
    domain = domain.strip().lower().lstrip("*.").split("/")[0]
    for path in ("/.well-known/security.txt", "/security.txt"):
        url = "https://" + domain + path
        try:
            status, ctype, data = _get(url, timeout)
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                continue
            return {"domain": domain, "status": "error", "fields": {}, "sha": None, "url": url}
        except Exception:
            return {"domain": domain, "status": "error", "fields": {}, "sha": None, "url": url}
        fields = parse(data)
        # Many sites answer every path with an HTML page; only count real security.txt files.
        if "html" in ctype.lower() or "contact" not in fields:
            continue
        sha = hashlib.sha256(repr(sorted(fields.items())).encode()).hexdigest()[:16]
        return {"domain": domain, "status": "ok", "fields": fields, "sha": sha, "url": url}
    return {"domain": domain, "status": "missing", "fields": {}, "sha": None, "url": None}


def fetch_all(domains, workers=8):
    domains = sorted({d.strip().lower().lstrip("*.") for d in domains if d and "." in d})
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        return {r["domain"]: r for r in ex.map(fetch, domains)}
