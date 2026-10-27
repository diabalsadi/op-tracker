# Local validation — 27 October 2026

Reviewed current upstream `8de3262` and made changes in an isolated checkout. No production database or real Jira export was used for testing. No CI workflows were added.

## Findings fixed

- Reopening an upgraded database after an archived TPM/QA replacement recreated legacy uniqueness indexes and failed. Keep active-only uniqueness on upgraded databases.
- Finalized reports reused live membership and could lose frozen delivery/targets after a backdated archive. Use preserved monthly membership for report inclusion and filters. Explicit revisions can now make a formerly eligible month inactive.
- Revision warnings compared totals only. Changed credit dates, score evidence, membership or eligibility now flag review even when totals match.
- Corrections between imports were deferred until a subsequent CSV. Add virtual calculation observations while preserving immutable source rows and the actual last-seen date.
- Follow-up policy changes during a blocked interval were ignored until a comment reset. Apply versions from their effective boundaries while retaining elapsed shared time and earlier deductions.
- An empty archived-owner roster could fall back to current members and continue charging the archived developer. Preserve explicitly empty ownership.
- A TPM-filtered report could include the same person's earlier developer target. Only developer role selections receive utilization targets.
- Late manual follow-ups validated current ownership. Validate the author against ownership at the occurrence time; offer historical responsible authors in ticket detail.
- Critical rewards used the completion-time country calendar. Use the developer calendar at the evidenced marked-Critical time. Expose the existing versioned deadline/reward policy in Targets.
- Backup connections were not explicitly closed. Close them before retention; stage and validate restores before replacement, and close the selected backup before pruning on Windows.
- New UI backups did not refresh the restore list. Refresh it after creation.
- Date presets lacked selected feedback. Add accessible pressed states and applied-date messages; use the same UTC calculation as report boundaries.

## Evidence

- 46 Python tests pass, including the original 29.
- Added regression cases cover restart after replacement, frozen membership and explicit inactive revisions, evidence-only changes, corrections without imports, corrupt and invalid-schema backup rejection, 30-backup retention, Arabic/spaced paths, follow-up policy changes, archived owners, role transitions, exact penalty boundaries and handover uniqueness, monthly bonuses/inactive-month averages, Critical evidence and calendar changes, mid-status rule changes, and a 32-member/1,000-ticket synthetic import.
- JavaScript syntax checks pass for app.js and extra.js.
- Chromium browser checks cover all pages/admin sections and six widths (320–1280 px), date presets/custom overrides/keyboard activation, file selection and mapping save/load, import preview/commit, downloads, manual-comment revision, corrections, team rename/archive/reactivation, member edit/archive/reactivation, monthly finalization/revision, backup creation/restore, rankings and annual profiles. Browser errors fail the test.
- Existing import tests cover identical, conflicting and out-of-order snapshots, retained tickets, repeated comments, wide Jira headers and aggregate duration mappings.

## Limits and remaining external validation

- Native Windows is unavailable on this Linux host. Python installation, start.bat, native browser opening, Windows file locking and native non-ASCII paths still require Windows execution. Linux path/restore tests do not certify Windows behavior.
- Actual roster, Jira identities, joining dates, production thresholds and the original Jira sample were not supplied to this checkout. No real onboarding or verification of production status IDs/duration units was performed.
- Source snapshots cannot establish unseen transitions or missing marked-Critical times. Warnings and audited corrections preserve this uncertainty.
- Keyboard preset activation was checked; this is not a complete accessibility audit or a formal contrast certification. The responsive check detects page overflow and black foreground text; it does not prove every visual detail.
- This is a regression and reliability pass, not a claim of production readiness or exhaustive coverage of every possible configuration/history combination.
