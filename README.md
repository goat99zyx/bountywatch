# BountyWatch

A daily email that tells bug bounty hunters what changed on the programs they hunt: programs that dropped off the public list (paused, closed or made private), assets added to or removed from scope, bounties switched on or off, reward ranges, eligibility and severity caps, and security.txt changes.

## How it works

1. **Collect.** Reads the public program listings of HackerOne, Bugcrowd, Intigriti and YesWeHack from the open [bounty-targets-data](https://github.com/arkadiyt/bounty-targets-data) dataset (MIT License, refreshed every 30 minutes). BountyWatch does not crawl the platforms itself. Optionally reads each HackerOne program website's `security.txt` (one GET per domain per day).
2. **Snapshot.** Stores the full state in SQLite (`data/bountywatch.sqlite`, about 8 MB per snapshot; the last 3 are kept).
3. **Diff.** Compares today with yesterday and names ten kinds of change:

| Type | Bucket |
|---|---|
| New program | opportunity |
| Program no longer listed | alert |
| Submission status changed | alert / opportunity |
| Bounties turned on or off | alert / opportunity |
| Reward range changed | alert / opportunity |
| Asset added to scope | opportunity |
| Asset removed from scope (or moved out of scope) | alert |
| Asset eligibility changed (bounty, submission, reward tier) | alert / opportunity / info |
| Severity cap changed | alert / opportunity |
| security.txt changed (published, removed, Expires/Policy/Contact changed, expired) | info |

   If a platform loses more than 20% of its programs (and at least 5) in one day, removals for that platform are held back as a likely data glitch.

4. **Report.** Builds one email per subscriber, filtered by their watchlist, plus a public free page (`index.html`, `feed.xml`) with headline numbers. Pro subscribers also get the day's changes as a JSON attachment.

## Run locally

```bash
python -m bountywatch snapshot                     # today's data
python -m bountywatch run --site site              # snapshot + diff + email previews in out/ + public page
python -m unittest discover -s tests -t .
```

Backfill from history (handy for a first comparison):

```bash
git clone --shallow-since="8 days ago" https://github.com/arkadiyt/bounty-targets-data src
python -m bountywatch snapshot --source "git:src@$(git -C src rev-list -1 --before='24 hours ago' HEAD)"
python -m bountywatch run --source "git:src@HEAD"
```

## Daily job (GitHub Actions)

`.github/workflows/daily.yml` runs every day at 06:17 UTC, keeps the database in the Actions cache, emails subscribers and publishes the free page to the `gh-pages` branch.

Repository secrets:

| Secret | Example |
|---|---|
| `SUBSCRIBERS_KEY` | private key that unlocks `subscribers/*.enc` (add subscribers with `python -m bountywatch add-subscriber --email ... --programs github,coinbase`) |
| `SMTP_USER`, `SMTP_PASS` | Brevo SMTP login and SMTP key (host defaults to smtp-relay.brevo.com:587; set `SMTP_HOST`/`SMTP_PORT` for another provider) |
| `MAIL_FROM` | `BountyWatch <digest@yourdomain.com>` |
| `MAIL_REPLY_TO` | where watchlist changes go |

Repository variable `SIGNUP_URL`: the checkout link shown on the free page.

Nothing is sent until the SMTP secrets and at least one real subscriber exist. `SUBSCRIBERS_JSON` (a JSON list) also works instead of encrypted files.

### Watchlist options

| Key | Meaning |
|---|---|
| `programs` | handles (`github`), keys (`h1:github`, `bc:openai`) or part of a name (4+ characters) |
| `domains` | assets containing these domains, e.g. `*.coinbase.com` |
| `platforms` | limit to `HackerOne`, `Bugcrowd`, `Intigriti`, `YesWeHack` |
| `all` | every program |
| `bounty_only` | skip programs that pay no bounties |

## Limits

- Public programs only; private invitations are not visible in the dataset.
- A program that disappears from the public list may be paused, closed or made private; the source data doesn't say which.
- The dataset's update timing sets the lower bound on how fresh the email can be.

Not affiliated with HackerOne, Bugcrowd, Intigriti or YesWeHack.
