# OP Tracker

Local CSV tracking application with a SQLite file database and an interactive web interface.

## Run

Requires Python 3.11+.

```bash
git clone https://github.com/diabalsadi/op-tracker.git
cd op-tracker
python server.py
```

Open http://127.0.0.1:8765. On Windows, use `py server.py`; install timezone data with `py -m pip install tzdata` if needed.

Start with Administration to create teams and members, then configure your own workflow rules and calendars. Imports support preview and commit. No employee data or database is included.

## Storage

Local data and backups are stored under `data/`, which Git ignores. Back up before changing configuration. Stop the server before restoring a SQLite backup. This is a localhost-only single-user application.

## Tests

```bash
python -m unittest discover -s tests -v
node --check web/app.js
```

## Initial version

Includes CSV snapshots, ticket history, configurable administration, date-range filters and charts. Some reports and historical policy/version controls remain under development. Rule, calendar, target or membership edits can recalculate results; the first version does not provide immutable monthly accounting records. Browser visual layout verification remains pending.

Chart.js is vendored with its license header. The app does not require remote services at runtime.
