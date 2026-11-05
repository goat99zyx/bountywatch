import copy
import unittest
from datetime import datetime, timezone

from bountywatch import diff as D
from bountywatch import report as R
from bountywatch import securitytxt as S
from bountywatch import sources


def raw():
    return {
        "hackerone": [{
            "handle": "acme", "name": "Acme", "url": "https://hackerone.com/acme", "website": "https://acme.com",
            "submission_state": "open", "offers_bounties": True,
            "targets": {"in_scope": [
                {"asset_identifier": "*.acme.com", "asset_type": "WILDCARD", "eligible_for_bounty": True,
                 "eligible_for_submission": True, "max_severity": "critical"},
                {"asset_identifier": "api.acme.com", "asset_type": "URL", "eligible_for_bounty": True,
                 "eligible_for_submission": True, "max_severity": "high"}],
                "out_of_scope": []}}],
        "bugcrowd": [{"name": "Beta", "url": "https://bugcrowd.com/engagements/beta", "max_payout": 5000,
                      "targets": {"in_scope": [{"type": "website", "target": "https://beta.io"}], "out_of_scope": []}}],
        "intigriti": [{"company_handle": "gam", "handle": "gamma", "name": "Gamma", "url": "u", "status": "open",
                       "min_bounty": {"value": 50, "currency": "EUR"}, "max_bounty": {"value": 1000, "currency": "EUR"},
                       "targets": {"in_scope": [{"type": "url", "endpoint": "gamma.eu", "impact": "Tier 1"}],
                                   "out_of_scope": []}}],
        "yeswehack": [{"id": "delta", "name": "Delta", "disabled": False, "min_bounty": 50, "max_bounty": 2000,
                       "targets": {"in_scope": [{"type": "web-application", "target": "delta.fr"}], "out_of_scope": []}}],
    }


class DiffTypes(unittest.TestCase):
    def setUp(self):
        self.a = raw()
        self.b = copy.deepcopy(self.a)

    def changes(self):
        return D.diff_programs(sources.normalize(self.a), sources.normalize(self.b))

    def types(self):
        return sorted(c["type"] for c in self.changes())

    def test_no_change(self):
        self.assertEqual(self.changes(), [])

    def test_program_added_and_removed(self):
        self.b["yeswehack"] = []
        self.b["hackerone"].append(dict(self.a["hackerone"][0], handle="newco", name="NewCo"))
        t = self.types()
        self.assertIn("program_removed", t)
        self.assertIn("program_added", t)

    def test_state_changed(self):
        self.b["hackerone"][0]["submission_state"] = "paused"
        c = self.changes()
        self.assertEqual([x["type"] for x in c], ["state_changed"])
        self.assertEqual(c[0]["bucket"], "alert")

    def test_bounty_changed(self):
        self.b["hackerone"][0]["offers_bounties"] = False
        self.assertEqual(self.types(), ["bounty_changed"])

    def test_reward_changed(self):
        self.b["intigriti"][0]["max_bounty"]["value"] = 3000
        c = self.changes()
        self.assertEqual([x["type"] for x in c], ["reward_changed"])
        self.assertEqual(c[0]["bucket"], "opportunity")

    def test_asset_added_removed_moved(self):
        self.b["hackerone"][0]["targets"]["in_scope"].append(
            {"asset_identifier": "pay.acme.com", "asset_type": "URL", "eligible_for_bounty": True,
             "eligible_for_submission": True, "max_severity": "critical"})
        api = self.b["hackerone"][0]["targets"]["in_scope"].pop(1)
        self.b["hackerone"][0]["targets"]["out_of_scope"].append(api)
        c = {x["type"]: x for x in self.changes()}
        self.assertIn("asset_added", c)
        self.assertTrue(c["asset_removed"]["detail"]["moved_out_of_scope"])

    def test_eligibility_and_severity(self):
        t = self.b["hackerone"][0]["targets"]["in_scope"][1]
        t["eligible_for_bounty"] = False
        t["max_severity"] = "medium"
        self.b["intigriti"][0]["targets"]["in_scope"][0]["impact"] = "No Bounty"
        self.assertEqual(self.types(), ["eligibility_changed", "eligibility_changed", "severity_changed"])

    def test_platform_glitch_guard(self):
        self.a["yeswehack"] = [dict(self.a["yeswehack"][0], id=f"p{i}") for i in range(10)]
        self.b["yeswehack"] = self.a["yeswehack"][:2]
        self.assertNotIn("program_removed", self.types())

    def test_ten_types(self):
        self.assertEqual(len(D.TYPES), 10)


class SecurityTxt(unittest.TestCase):
    TXT = ("Contact: mailto:security@acme.com\nExpires: 2026-11-04T00:00:00Z\n"
           "Policy: https://acme.com/policy\n# comment\n")

    def res(self, txt, status="ok"):
        f = S.parse(txt)
        return {"domain": "acme.com", "status": status, "fields": f, "sha": str(sorted(f.items())), "url": "x"}

    def test_parse(self):
        f = S.parse(self.TXT)
        self.assertEqual(f["contact"], ["mailto:security@acme.com"])
        self.assertEqual(S.expires_at(f).year, 2026)

    def test_changed_and_expired(self):
        a = {"acme.com": self.res(self.TXT)}
        b = {"acme.com": self.res(self.TXT.replace("2026-11-04", "2027-11-04"))}
        c = D.diff_securitytxt(a, b)
        self.assertEqual(len(c), 1)
        self.assertIn("Expires", c[0]["summary"])
        now = datetime(2026, 11, 5, tzinfo=timezone.utc)
        since = datetime(2026, 11, 3, tzinfo=timezone.utc)
        c = D.diff_securitytxt(a, copy.deepcopy(a), now=now, since=since)
        self.assertTrue(c and c[0]["detail"].get("expired"))

    def test_errors_ignored(self):
        a = {"acme.com": self.res(self.TXT)}
        b = {"acme.com": dict(self.res(""), status="error")}
        self.assertEqual(D.diff_securitytxt(a, b), [])


class Watchlist(unittest.TestCase):
    def test_matching(self):
        progs = sources.normalize(raw())
        a = raw()
        b = copy.deepcopy(a)
        b["hackerone"][0]["submission_state"] = "paused"
        b["bugcrowd"][0]["max_payout"] = 9000
        ch = D.diff_programs(sources.normalize(a), sources.normalize(b))
        r = R.build({"watch": {"programs": ["acme"]}}, ch, progs, "today", global_new=[])
        self.assertEqual(r["n"], 1)
        self.assertIn("check before you submit", r["subject"])
        r = R.build({"watch": {"all": True, "platforms": ["Bugcrowd"]}}, ch, progs, "today", global_new=[])
        self.assertEqual(r["n"], 1)
        r = R.build({"watch": {"all": True}}, ch, progs, "today", global_new=[], days_left=2, renew_url="https://x")
        self.assertIn("ends in 2 days", r["text"])


if __name__ == "__main__":
    unittest.main()
