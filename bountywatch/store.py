"""SQLite snapshots: one row set per day, like a photo of every public program."""
import json
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots(
  id INTEGER PRIMARY KEY, taken_at TEXT NOT NULL, source TEXT, label TEXT);
CREATE TABLE IF NOT EXISTS programs(
  snapshot_id INTEGER, pkey TEXT, platform TEXT, name TEXT, url TEXT, website TEXT, state TEXT,
  offers_bounties INTEGER, min_reward REAL, max_reward REAL, currency TEXT,
  PRIMARY KEY(snapshot_id, pkey));
CREATE TABLE IF NOT EXISTS assets(
  snapshot_id INTEGER, pkey TEXT, akey TEXT, in_scope INTEGER, type TEXT,
  bounty INTEGER, submit INTEGER, severity TEXT, tier TEXT,
  PRIMARY KEY(snapshot_id, pkey, akey, in_scope));
CREATE TABLE IF NOT EXISTS sectxt(
  snapshot_id INTEGER, domain TEXT, status TEXT, sha TEXT, fields TEXT, url TEXT,
  PRIMARY KEY(snapshot_id, domain));
CREATE TABLE IF NOT EXISTS changes(
  snapshot_id INTEGER, prev_snapshot_id INTEGER, seq INTEGER, type TEXT, bucket TEXT,
  pkey TEXT, platform TEXT, program TEXT, summary TEXT, detail TEXT,
  PRIMARY KEY(snapshot_id, seq));
CREATE INDEX IF NOT EXISTS assets_snap ON assets(snapshot_id, pkey);
"""


def b2i(v):
    return None if v is None else int(bool(v))


def i2b(v):
    return None if v is None else bool(v)


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)

    def save_snapshot(self, programs, sectxt=None, source="", label="", taken_at=None):
        taken_at = taken_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
        cur = self.db.execute("INSERT INTO snapshots(taken_at, source, label) VALUES(?,?,?)",
                              (taken_at, source, label))
        sid = cur.lastrowid
        self.db.executemany(
            "INSERT INTO programs VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            [(sid, p["key"], p["platform"], p["name"], p["url"], p.get("website"), p["state"],
              b2i(p["offers_bounties"]), p["min_reward"], p["max_reward"], p["currency"])
             for p in programs.values()])
        self.db.executemany(
            "INSERT OR IGNORE INTO assets VALUES(?,?,?,?,?,?,?,?,?)",
            [(sid, p["key"], a["akey"], int(a["in_scope"]), a["type"], b2i(a["bounty"]), b2i(a["submit"]),
              a["severity"], a["tier"]) for p in programs.values() for a in p["assets"]])
        if sectxt:
            self.db.executemany(
                "INSERT INTO sectxt VALUES(?,?,?,?,?,?)",
                [(sid, d, r["status"], r["sha"], json.dumps(r["fields"], sort_keys=True), r["url"])
                 for d, r in sectxt.items()])
        self.db.commit()
        return sid

    def snapshot_ids(self):
        return [r[0] for r in self.db.execute("SELECT id FROM snapshots ORDER BY id")]

    def snapshot_info(self, sid):
        r = self.db.execute("SELECT id, taken_at, source, label FROM snapshots WHERE id=?", (sid,)).fetchone()
        return dict(zip(("id", "taken_at", "source", "label"), r)) if r else None

    def load(self, sid):
        progs = {}
        for r in self.db.execute("SELECT pkey, platform, name, url, website, state, offers_bounties, "
                                 "min_reward, max_reward, currency FROM programs WHERE snapshot_id=?", (sid,)):
            progs[r[0]] = {"key": r[0], "platform": r[1], "name": r[2], "url": r[3], "website": r[4],
                           "state": r[5], "offers_bounties": i2b(r[6]), "min_reward": r[7],
                           "max_reward": r[8], "currency": r[9], "assets": []}
        for r in self.db.execute("SELECT pkey, akey, in_scope, type, bounty, submit, severity, tier "
                                 "FROM assets WHERE snapshot_id=?", (sid,)):
            if r[0] in progs:
                progs[r[0]]["assets"].append({"akey": r[1], "in_scope": bool(r[2]), "type": r[3],
                                              "bounty": i2b(r[4]), "submit": i2b(r[5]),
                                              "severity": r[6], "tier": r[7]})
        sec = {}
        for r in self.db.execute("SELECT domain, status, sha, fields, url FROM sectxt WHERE snapshot_id=?", (sid,)):
            sec[r[0]] = {"domain": r[0], "status": r[1], "sha": r[2], "fields": json.loads(r[3] or "{}"),
                         "url": r[4]}
        return progs, sec

    def save_changes(self, sid, prev_sid, changes):
        self.db.execute("DELETE FROM changes WHERE snapshot_id=?", (sid,))
        self.db.executemany(
            "INSERT INTO changes VALUES(?,?,?,?,?,?,?,?,?,?)",
            [(sid, prev_sid, i, c["type"], c["bucket"], c["pkey"], c["platform"], c["program"],
              c["summary"], json.dumps(c.get("detail", {}), sort_keys=True)) for i, c in enumerate(changes)])
        self.db.commit()

    def prune(self, keep=45):
        ids = self.snapshot_ids()
        old = ids[:-keep] if len(ids) > keep else []
        for t in ("programs", "assets", "sectxt", "changes"):
            self.db.executemany(f"DELETE FROM {t} WHERE snapshot_id=?", [(i,) for i in old])
        self.db.executemany("DELETE FROM snapshots WHERE id=?", [(i,) for i in old])
        self.db.commit()
        if old:
            self.db.execute("VACUUM")
