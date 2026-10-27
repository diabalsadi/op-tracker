# OP Tracker — Confirmed Business Decisions

Date: 27 October 2026

This file records confirmed choices made after the initial requirements questionnaire. BUSINESS_REQUIREMENTS.md remains the full specification. These are requirements and decisions, not a certification of implementation completeness.

## Branding and interaction

- Name and identity: Optimum Partners.
- Use the official supplied logo and website colors: mint `#66D1A3` and charcoal `#1F1F1F`.
- Glass-style dark surfaces, explicit light foreground colors, consistent spacing and responsive layouts.
- Montserrat headings and Inter interface text when available; local system fallbacks keep the application independent of remote fonts.
- Use Chart.js for interactive charts.
- Clicking a member opens annual monthly history. Clicking a month reveals its breakdown; clicking a ticket opens its lifecycle and follow-ups.

## Periods and geography

- Start/end date pickers support custom ranges, combined months and quarters.
- Monthly rewards remain monthly; longer-period performance scores average monthly records.
- Utilization targets scale with period duration and eligible membership, with working-calendar proration for partial periods.
- Country filters and country labels are required on member reporting.
- Jordan uses Friday/Saturday weekends. Dominican Republic and Armenia use Saturday/Sunday. Holidays are configured by country.

## Daily imports

- Imports occur daily and preserve each source snapshot.
- Match tickets by Jira key. Later status, assignee, priority, estimate and comment evidence updates the same tracked ticket.
- Detect teams from Jira assignees and member mappings. No team selection per uploaded file is needed.
- Preserve prior snapshots and avoid duplicated comments or completion credit.
- Tickets missing from a later file remain in the tracker.
- Clearly identify changes detected between snapshots; do not invent exact historical transition times.
- Encoded Time in Status totals require verified status-ID and unit mappings and cannot prove chronological history.

## Operation and delivery

- Run on one local computer with a SQLite file database and no login.
- Keep real Jira exports, member data and backups out of source control.
- The hosted sample-data prototype is separate from the local application.
- Repository: https://github.com/diabalsadi/op-tracker
- CI workflows are not wanted; run tests locally.
- Maintain an honest distinction between implemented features, verified behavior and source/platform limitations.

## Shared QA and TPM assignments

- Confirmed on 27 October 2026: the same QA or TPM member may be assigned to multiple teams through a Teams multi-select in member administration.
- A QA member can be Primary in one team and Secondary in another. Each team retains one TPM and one member in each QA slot.
- Developers retain one team at a time. Assignments remain effective-dated, and a shared member has one identity and one monthly performance record rather than duplicate person records.
