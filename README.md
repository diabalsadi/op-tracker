# OP Tracker

A local Jira CSV tracker with a SQLite file database and an interactive web interface. No login or external service is required. The database starts empty; no employee records, Jira exports, or personal data are included in the repository.

## Start

Install Python 3.11 or newer, then:

```bash
git clone https://github.com/diabalsadi/op-tracker.git
cd op-tracker
python -m pip install -r requirements.txt
python server.py --open
```

On Windows, use `py -3` instead of `python` if needed. After installing dependencies, double-click **start.bat**. On macOS/Linux, use `sh start.sh`. Open **http://127.0.0.1:8765** if your browser does not open automatically. The application binds only to localhost.

Optional arguments:

```bash
python server.py --port 9000 --db path/to/tracker.sqlite3
```

## Initial setup

1. **Administration → Teams:** create your teams.
2. **Members:** enter names, exact Jira account IDs, countries, roles and assignments. Developers have one team. QA and TPM members use the Teams multi-select dropdown to choose multiple teams; QA can hold a different Primary/Secondary position in each team. Each team still has one TPM and one person per QA slot. Set each person's effective joining date correctly before importing historical exports. Changes create effective-dated versions; archiving/reactivating retains inactive periods and prior records.
3. **Calendars:** choose weekend days and add country holidays, including date ranges. Existing dates can be edited or removed.
4. **Workflow:** imported status and priority names appear automatically. Map unconfigured statuses to active, paused, completed, cancelled or backlog categories and set accountable roles. Unconfigured statuses do not generate delivery credit or deductions. In Priority configuration, choose which priority names qualify for Critical rewards. Existing configuration is preserved.
5. **Workflow rules:** define the severity/estimate combinations, durations and deductions your organization chooses. Effective dates preserve earlier rule versions.
6. **Targets:** review your delivery and follow-up policy. Policy changes have effective dates. Targets also configures the Critical completion window and reward per owner.
7. **Sprints:** optionally define reporting periods and team scope.
8. **Imports:** preview and commit your daily CSV snapshot.

## Daily imports

Ticket keys identify records. A later CSV appends a snapshot and updates current status, ownership and comments. Earlier observations are preserved. Reimporting an identical snapshot is a no-op. Tickets absent from a filtered export are not deleted or completed. Out-of-order imports are ordered chronologically; conflicting ticket values at the same snapshot time are rejected.

The importer accepts UTF-8 or Windows-1252 files, repeated comment columns, common Jira header aliases, and comma/tab/semicolon delimiters. Column overrides and source timezone can be saved as import profiles. Select the CSV's actual timezone for dates without offsets; timestamps with explicit offsets remain authoritative. The snapshot picker uses your browser's local time and converts it to UTC.

Jira comments may contain `timestamp;author;body` text or JSON:

```json
[{"author":"jira-account-id","at":"2026-10-20T09:00:00Z","body":"Progress update"}]
```

Unattributable or undated comments remain visible but cannot establish a follow-up deadline. Unmapped assignees and missing estimates appear in import warnings. Use member setup and audited ticket corrections to repair these inputs.

## Reports

- Start/end date pickers combine months, quarters or custom periods. Presets select the current month, quarter or year through today, with a highlighted selection and the applied UTC dates. In the first month of a quarter, month-to-date and quarter-to-date share the same start date. Reporting endpoint dates and event grouping use UTC; working-time calculations use country calendars.
- Historical member assignments and active periods determine period targets. Partial months are prorated using working time.
- Monthly performance records are calculated separately. Multi-month views average eligible monthly records; selecting part of a month does not create another score baseline.
- Individual, role and team rankings have separate performance/utilization views. Roles without delivery targets are not assigned utilization values.
- Annual member profiles include interactive monthly charts, evidence and record status. Each profile also lists its latest assigned/accountable tickets across all dates, with counts and current SP totals by status. Select a status or click its summary row to filter the ticket list; click a ticket key to inspect its lifecycle. These status totals are separate from completed delivery credit. Months before joining or during inactive periods are excluded.
- Delivery reports include observed status durations versus configured allowances. Click a ticket for snapshots, changes, comments, score events and corrections.
- The current workflow snapshot counts only tickets whose current Jira assignee matches an active configured member, using that member’s team/country filters. Unmapped tickets remain available in Tickets and Imports.
- CSV report exports use the selected filters. Workflow charts show latest observed state and are labeled accordingly.

## Monthly history and corrections

Elapsed months are finalized when the app next reads the database. Finalized records preserve delivery credits, daily targets, events and scores. New evidence does not silently replace them: affected months are flagged as needing review. Use **Administration → Monthly records** to create an explicit revision with a reason; earlier versions remain available.

Configuration history is visible in Administration. Ticket corrections and manual-comment revisions retain original source evidence and audit entries. A reopened ticket does not create a second delivery credit.

An export containing aggregate Time in Status data does not establish chronological transitions. The app retains encoded totals and provides status-ID/unit mapping controls. Verify those mappings before interpreting hours. Exact historical transitions or the moment a priority changed cannot be recovered from a current-state-only export; supply trustworthy history or an audited correction instead of guessing.

## Data and backup

`data/tracker.sqlite3` contains configuration, original CSV contents, snapshots, comments, audit history and monthly records. `data/` is excluded from Git. Automatic consistent backups run before imports and important historical operations; the newest 30 are retained in `data/backups/`.

**Administration → Backup & restore** creates backups and restores a listed snapshot after explicit confirmation. Restore validates integrity, references and application readability in an isolated copy, then creates a safety backup before replacing the active database. For manual restoration, stop the server, retain a copy of the current database, replace the database file with your chosen backup, and restart.

This is a single-operator localhost application. The separately hosted design prototype uses sample data and is not connected to your database.

## Validation

Run locally; no CI workflow is installed:

```bash
python -m unittest discover -s tests -v
node --check web/app.js
node --check web/extra.js
```

Optional browser regression check (Node.js required):

```bash
npm install --no-save playwright
npx playwright install chromium
node tests/browser_smoke.mjs
```

The browser check starts an isolated temporary database, exercises navigation, date presets and custom dates, file selection and mapping profiles, import preview/commit, exports, corrections, comment revisions, archive/reactivation, monthly revisions and UI restore. It uses real Chart.js and scans desktop/mobile widths. `CHROMIUM_PATH`, `PLAYWRIGHT_MODULE`, `PYTHON`, `TEST_PORT`, and `QA_SCREENSHOTS` optionally select an existing browser/runtime or screenshot directory. Native Windows execution must be checked on a Windows machine; the startup scripts and timezone dependency are provided.

Chart.js is vendored with its license header. Fonts use installed Inter/Montserrat where available and system fallbacks; there are no external font or analytics requests.
