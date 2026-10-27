# OP Tracker

A local Jira CSV tracker for Optimum Partners. SQLite persistence, daily snapshots, member/team administration, country calendars, configurable duration rules, Chart.js dashboards, and ticket history. No login or cloud service is required. The database starts empty; no real Jira or employee data is committed to this repository.

## Run

Install Python 3.11 or newer, then:

```bash
git clone https://github.com/diabalsadi/op-tracker.git
cd op-tracker
python server.py
```

Open **http://127.0.0.1:8765**. On Windows, `py server.py` also works. If Windows cannot find timezone data, run `py -m pip install tzdata` once. The server listens only on localhost. To use another port or database:

```bash
python server.py --port 9000 --db path/to/tracker.sqlite3
```

Python's standard library supplies the HTTP server, CSV parser, and SQLite database. Chart.js 4.4.8 is vendored in `web/vendor/`, including its MIT copyright/license header. The supplied Optimum Partners logo is retained for this internal project. Interface typography uses installed system fonts, with Montserrat/Inter when available; no remote font requests are made.

## First setup

1. Open **Administration → Teams** and create your teams.
2. Under **Members**, enter each person's name, exact Jira account ID, country, role, and team. A team supports multiple developers, one TPM, and primary/secondary QA.
3. Under **Calendars**, configure weekends (Monday=0 … Sunday=6), timezones, and holidays. Jordan defaults to Friday/Saturday; DR and Armenia to Saturday/Sunday.
4. Under **Workflow rules**, define exact status + severity + SP combinations and their allowed working days / penalties. No rule is enabled by default; example values are not treated as approved production thresholds.
5. Under **Targets**, review the 16-SP monthly target and shared 3-working-day follow-up settings.
6. Open **Imports**, choose your daily CSV and its snapshot timestamp, preview warnings, then commit. Map nonstandard column headers in the optional mapping panel.

## Daily CSV updates

Tickets match by Jira key, not by row position. Importing a new daily snapshot updates the ticket's current state and preserves prior observations. Comments are deduplicated by author, occurrence timestamp, and content. A file's absence of a ticket never removes or completes that ticket. Reimporting an identical file at the same snapshot time is a no-op. Out-of-order imports are ordered chronologically; conflicting values for one ticket at the same timestamp are rejected.

Supported standard fields: `Issue key`, `Summary`, `Status`, `Assignee Id`, `Story Points`, `Priority`, `Resolved`, `Critical At`, and one or more `Comment` columns. Common Jira story-point header aliases are recognized. Header overrides are available in the import form. CSV timestamps should use ISO 8601 with timezone; naive export timestamps are interpreted as UTC. The upload form converts your browser-local snapshot time to UTC. CSV delimiter is comma; export as UTF-8.

Comments may be JSON objects/arrays:

```json
[{"author":"jira-account-id","at":"2026-10-20T09:00:00Z","body":"Contacted the vendor"}]
```

Or Jira-style `timestamp;author;body` text. Comments missing reliable author/time stay visible but cannot reset follow-up deadlines. `Resolved` supplies historical completion evidence; a ticket already Done in the first import without a completion date receives no arbitrary current-month credit. Critical bonuses require a trustworthy `Critical At` timestamp. Encoded aggregate Time in Status values are not decoded into invented chronological history.

## Reporting

- **Start date / End date** filters support combined months and quarters. Shortcuts select this month, quarter, or year through today.
- Delivery uses first-completion SP once per ticket; reopening neither removes nor duplicates credit.
- Utilization uses completed SP divided by the target. Full months have a target of 16 SP per developer; partial-month targets are prorated using each developer's working days and holidays.
- Performance starts at 100 for each month, adds full 20%-over-100 utilization steps worth 10 points, adds qualifying Critical rewards, and subtracts delay/follow-up deductions.
- Multi-month views average monthly scores. A partial-month filter includes that month's entire monthly performance record; the UI labels this behavior. Utilization bonuses are never re-awarded for selecting a longer period.
- Member profiles show annual monthly charts; click a month for supporting credits/events, and click a ticket for its lifecycle.
- QA/TPM have no SP utilization. Their performance is visible separately. Team/country filters use member mappings.
- Charts show latest observed workflow state and label it accordingly. Stale or incomplete snapshots require operator review; live penalties assume the last observed status continues.

## Data, backup, and privacy

`data/tracker.sqlite3` holds configurations, original CSV contents, snapshots, manual comments, and audit records. `data/` is ignored by Git. Automatic consistent SQLite backups run before imports; 30 are retained in `data/backups/`. Administration offers a manual backup. To restore, **stop the server**, keep a copy of the current database, replace `data/tracker.sqlite3` with the chosen backup, and restart. Do not copy a live database file as a backup.

The app is a single-operator local tool. Do not bind it to a public interface or use it as a production multi-user server. No emails, Jira writes, or external analytics occur. The previously shared hosted design preview is separate from this local application.

## Tests

```bash
python -m unittest discover -s tests -v
node --check web/app.js
```

## First-version limits and next work

This is a working foundation, not a claim that every requirement in the business specification is complete:

- No sprint-specific reports, team ranking board, archived-member lifecycle, or administration of arbitrary role responsibility maps yet. Individual rankings and team-filtered aggregates work.
- Country/team/member edits are audited, and imported ticket ownership snapshots preserve score attribution. Reporting headcount and country filters still use current membership; effective-dated membership targets and joining/leaving proration remain to be implemented.
- Rule edits are audited but rule-version/month-finalization locking is not yet implemented. Settings and calendar changes recalculate reports. Export reports before changing policy if you need a frozen record.
- Monthly scores include every elapsed calendar month in the selected year; member active dates are not implemented. Future months are excluded.
- Reporting dates use UTC for credit/event grouping; working-time calculations use configured country timezones. Shared follow-up dates use Asia/Amman.
- Normal timers use first observed transitions, preserving uncertainty. Encoded Jira Time in Status decoding, exact transition histories, configurable priority/status categories, historical ownership corrections, import-profile persistence, and manual evidence corrections need further work.
- The local app supports persisted imports; the hosted preview remains sample-only. Desktop screenshots and browser layout QA require an available browser; automated domain tests cover the core ingestion/calculation behaviors.

The complete agreed business specification is in [docs/BUSINESS_REQUIREMENTS.md](docs/BUSINESS_REQUIREMENTS.md). Date-range filters supersede its original month-only UI description.
