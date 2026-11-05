"""Subscriber records, stored encrypted in the public repo.

Each subscriber is one file, subscribers/<id>.enc, encrypted with the public certificate
subscribers/cert.pem (OpenSSL CMS, AES-256). Anyone with the repo can add or renew a
subscriber; only the daily job, which holds the private key in the SUBSCRIBERS_KEY secret,
can read them. Email addresses never appear in the repo in plain text.
"""
import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

DIR = Path("subscribers")
CERT = DIR / "cert.pem"


def sub_id(email):
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:16]


def encrypt(record, cert=CERT):
    p = subprocess.run(["openssl", "cms", "-encrypt", "-aes256", "-outform", "PEM", str(cert)],
                       input=json.dumps(record, sort_keys=True).encode(), capture_output=True, check=True)
    return p.stdout


def decrypt(blob, key_pem):
    with tempfile.NamedTemporaryFile("w", delete=False) as kf:
        kf.write(key_pem)
        kpath = kf.name
    try:
        p = subprocess.run(["openssl", "cms", "-decrypt", "-inform", "PEM", "-inkey", kpath],
                           input=blob, capture_output=True, check=True)
        return json.loads(p.stdout)
    finally:
        os.unlink(kpath)


def save(record, directory=DIR):
    directory = Path(directory)
    directory.mkdir(exist_ok=True)
    path = directory / f"{sub_id(record['email'])}.enc"
    path.write_bytes(encrypt(record, directory / "cert.pem"))
    return path


def load_all(key_pem, directory=DIR):
    out = []
    for f in sorted(Path(directory).glob("*.enc")):
        try:
            out.append(decrypt(f.read_bytes(), key_pem))
        except Exception:
            print(f"could not read {f.name}")
    return out


def make_record(email, programs=(), domains=(), all_programs=False, bounty_only=False, days=30,
                plan="standard", start=None):
    start = start or datetime.now(timezone.utc).date()
    return {"email": email.strip(), "plan": plan, "active": True,
            "expires": (start + timedelta(days=days)).isoformat(),
            "watch": {"programs": [p.strip() for p in programs if p.strip()],
                      "domains": [d.strip() for d in domains if d.strip()],
                      "all": bool(all_programs), "bounty_only": bool(bounty_only)}}
