# OP Team Tracker — Business Requirements

Version: 1.1  
Date: 27 October 2026  
Owner: Diab Alsadi  
Deployment: local computer only, without login  
Document purpose: implementation-ready business specification, not an implemented application.

## 1. Decision status

**Confirmed** means explicitly agreed during requirements gathering. **Recommended default** means a remaining decision resolved using the owner's instruction to proceed with recommendations. Recommended defaults form the initial implementation specification and remain editable where appropriate.

The confirmed business identity is Optimum Partners, using the supplied official logo, mint #66D1A3 and charcoal #1F1F1F. The approved direction is a glass-style dark dashboard with readable light text, Montserrat headings and Inter body text where available, with system font fallbacks. All controls, values, chart labels and tables must preserve contrast. See BUSINESS_DECISIONS.md for subsequent confirmed decisions.

## 2. Business objective

Create a local team tracking system driven by daily Jira CSV imports. Make delivery, workflow delays, follow-up discipline, utilization, and performance visible at member and team levels. Provide an explainable record of how every score, bonus, penalty, and story-point total was calculated.

Keep three measures separate:

1. **Delivery:** original ticket story points credited on completion.
2. **Developer utilization:** delivered story points compared with a 16-SP monthly target.
3. **Performance score:** a monthly baseline of 100, adjusted by bonuses and penalties; scores may exceed 100.

## 3. Initial scope and boundaries

### Confirmed scope

- One computer, one local operator, no login.
- Local application files and a SQLite database stored as a local file.
- Daily CSV ingestion with preserved snapshots.
- Teams, developers, TPMs, primary QA, and secondary QA.
- Configurable workflow statuses and sprint/reporting periods.
- Story-point delivery, utilization, performance, and ranking dashboards.
- Member profiles with a full year of monthly utilization and score history.
- Country calendars and configurable public holidays.
- Imported comments and manual follow-up entries.
- A complete available lifecycle view for each ticket, accessible by clicking the ticket.
- Admin configuration for business rules.

### Recommended initial boundaries

- No cloud hosting, Jira API synchronization, automated Jira changes, email delivery, or external notifications.
- No employee self-service, network sharing, or authentication in this version. Bind the application to localhost by default.
- No individual leave/absence module; country weekends and holidays determine availability.
- In-app alerts and local exports only.
- Support multiple Jira projects through project-specific import mappings and workflow configuration.
- Historical detail is limited to evidence in imported data and subsequent observations; do not invent transitions or comments.

## 4. People, teams, and ownership

### Confirmed structure

Members are created manually with a name, Jira identity, role, and team. Each member has a country and corresponding working calendar. One team can contain people in different countries.

Each team contains:

| Role | Team structure | Main responsibility |
| --- | --- | --- |
| Developer | Multiple developers | Ticket progress until Ready for Release; includes QA-stage delays |
| Primary QA | One | QA and Ready for Release stages |
| Secondary QA | One | Same accountability and rewards as primary QA |
| TPM | One | All active workflow stages and follow-up discipline |

The ticket's Jira assignee identifies its developer. The developer's team determines TPM and both QA owners. Both QA members receive applicable QA penalties and critical-ticket rewards.

### Recommended ownership defaults

- Store team membership and ticket ownership as effective-dated history.
- Retain penalties against the people responsible when the delay occurred. Reassignment affects future accountability only.
- A new owner inherits elapsed ticket time; reassignment does not restart the status timer.
- Credit delivered SP to the developer and team at the first evidenced Done transition. Preserve that attribution after later reassignment.
- If the Jira assignee is a QA or TPM, retain the most recent mapped developer owner; require a manual override when no developer can be identified.
- Unmapped Jira identities enter an exception queue. Never silently assign a person or deduct from an unknown owner.
- Prevent the same person from occupying both QA slots on one team. Avoid duplicate awards or penalties to the same person for the same event if other role overlaps exist.
- Archive members and teams instead of removing their history.

## 5. Workflow and reporting cycles

### Confirmed behavior

Support both workflow cycles and sprint/reporting periods. Admins control status names, ordering, role accountability, time allowances, and deductions by severity and SP.

### Recommended initial status template

This template must be mapped to actual Jira statuses during setup; it does not assert that these are the CSV's exact status names.

| Status category | Developer | Both QAs | TPM | Timer |
| --- | --- | --- | --- | --- |
| To Do / active backlog | Yes | No | Yes | Configured normal timer |
| In Progress | Yes | No | Yes | Configured normal timer |
| Code Review | Yes | No | Yes | Configured normal timer |
| QA | Yes | Yes | Yes | Configured normal timer |
| Ready for Release | No | Yes | Yes | Configured normal timer |
| Blocked / On Hold | Follow-up | No | Follow-up | Shared follow-up timer only |
| Done | No | No | No | Stopped |
| Cancelled | No | No | No | Stopped; no delivery credit |

Admins can distinguish an uncommitted backlog from active To Do work so an unlimited backlog does not automatically generate penalties. No normal penalty applies until a status has an explicit active rule.

Recommended sprint records contain name, project/team scope, start date, and end date. Sprint filters organize delivery and workflow reporting but do not replace the monthly utilization target.

## 6. Country calendars and working time

### Confirmed calendars

| Country | Weekend |
| --- | --- |
| Jordan | Friday–Saturday |
| DR | Saturday–Sunday |
| Armenia | Saturday–Sunday |

Recommended interpretation: DR means Dominican Republic; use that country label in configuration and allow it to be renamed. Holidays are maintained manually by country and date, including multi-day ranges. No automatic holiday source is required.

### Recommended time semantics

- Store timestamps in UTC and render them in the relevant configured timezone.
- Configure a timezone for each country; use Asia/Amman, America/Santo_Domingo, and Asia/Yerevan as initial values.
- Use working-day units rather than contractual working hours. A full eligible local weekday contributes one day; partial eligible dates contribute the elapsed fraction of the local day.
- Weekends and configured holidays contribute zero elapsed working time.
- Normal delay calculations use each accountable person's own country calendar. Therefore two owners can reach their thresholds at different instants.
- At exactly the allowed duration, show a deadline reached; a breach begins only once eligible working time exceeds it.
- A daily penalty increment represents another complete working day elapsed after the initial breach. Evaluate penalties by their effective time, not the time the dashboard was opened.
- Show the calendar, allowance, elapsed time, and next deduction time on ticket detail.

## 7. Delivery and utilization

### Confirmed rules

- Only tickets reaching **Done** earn delivered SP.
- The target is **16 SP per developer per calendar month**, not per sprint.
- Reopening a ticket does not remove its previously credited SP.
- Completing the same ticket again does not award SP again.
- Critical-ticket score rewards do not increase delivered SP or utilization.
- QA and TPM have no SP utilization target and do not appear in utilization rankings.

### Formulas

```text
Monthly developer utilization (%) = credited delivered SP / 16 × 100
Quarterly developer utilization (%) = credited delivered SP / 48 × 100
Yearly developer utilization (%) = credited delivered SP / 192 × 100

Team monthly utilization (%) = developers' credited delivered SP
                               / (16 × number of eligible developers) × 100
```

Confirmed weekly calculation: prorate the monthly 16-SP target by working days. A five-working-day week within a month containing twenty working days has a target of 4 SP.

Recommended general calculation for partial dates and weeks crossing month boundaries:

```text
Period target = sum across intersecting months:
  16 × member's working-day units inside the selected period and month
     / member's total working-day units in that full month

Period utilization (%) = delivered SP credited inside period / period target × 100
```

Use the full 16-SP target for a full eligible month. For joining, leaving, or changing teams mid-month, prorate eligible membership days; sum these individual targets for team utilization. Do not use today's headcount to recalculate historical team targets.

### Recommended delivery evidence rules

- Freeze SP at the first credited completion. Later SP edits require an explicit audited correction.
- Use an authoritative resolution/status-history timestamp where available. Otherwise record the first observed Done timestamp as an estimate and show its evidence quality.
- On the first import, an already-Done ticket with no reliable completion date belongs in historical undated delivery; do not assign it arbitrarily to the current month.
- A ticket without SP remains visible but contributes no numeric delivery credit until corrected; flag it as missing rather than silently treating its estimate as known zero.
- Display N/A when the target is zero; never divide by zero.

## 8. Monthly performance score

### Confirmed model

```text
Monthly score = 100 + utilization bonus + critical-ticket bonuses − penalties

Multi-month score = arithmetic average of the included monthly scores
```

Scores can exceed 100. Preserve monthly records and show monthly history for a full selected year.

### Utilization bonus — developers only

```text
Monthly utilization bonus = 10 × floor(max(0, utilization (%) − 100) / 20)
```

| Monthly utilization | Score bonus |
| --- | --- |
| 100%–less than 120% | 0 |
| 120%–less than 140% | +10 |
| 140%–less than 160% | +20 |
| 160%–less than 180% | +30 |

Calculate once per calendar month. Show a provisional value during the current month, finalize at month-end, and do not award another utilization bonus when viewing a quarter or year. Use unrounded utilization for threshold checks.

### Recommended score defaults

- No lower floor and no upper cap initially; preserve the raw score and its breakdown. Admins may configure a future cap/floor prospectively.
- Average eligible monthly records equally. Exclude months before joining or after leaving rather than filling them with zero or 100.
- For a partial-month dashboard filter, show the containing monthly score clearly labeled; weekly activity reports show score events within the week rather than creating a separate 100-point weekly baseline.
- Finalize elapsed months on next application startup or calculation, without requiring a constantly running background service.
- Late evidence can generate an audited revised monthly version. Preserve the prior calculation and the reason for revision.

## 9. Critical-ticket reward

### Confirmed rule

A ticket marked Critical that reaches Done within **2 working days of being marked Critical** awards **+1 performance-score point** to its developer, TPM, primary QA, and secondary QA. This is a score reward, not SP delivery credit.

### Recommended defaults

- Use the developer's country calendar at the time the ticket is marked Critical as the common reward clock. Show this choice in the reward explanation.
- Award at most once per ticket, to the eligible owners at its first credited Done event.
- Freeze the first evidenced Critical timestamp for the reward clock. Toggling priority does not reset the clock; cancellation of Critical status before completion makes the automatic reward ineligible unless corrected manually with a reason.
- If the timestamp when the ticket became Critical is unavailable, do not infer it from the current priority. Flag the reward as unverified and allow a sourced manual correction.
- Reopened tickets do not receive a second completion reward.
- Critical threshold, reward amount, and priority mapping are configurable.

## 10. Normal workflow delay penalties

### Confirmed policy

Admins configure the permitted duration and deduction values by **status, severity, and story points**. The agreed initial deduction pattern is:

```text
At first breach: −2 score points
Each additional complete overdue working day: −1 score point
```

Apply independently to all accountable owners. In QA, this includes the developer, both QAs, and TPM. In Ready for Release, it includes both QAs and TPM, excluding the developer.

### Recommended rule behavior

- Rule fields: project/workflow, status, severity, SP value or band, allowance, initial deduction, daily increment, accountable roles, effective date, and enabled flag.
- Resolve rules by explicit specificity: exact status/severity/SP rule, then defined wildcard fallbacks. Reject overlapping equally specific rules.
- Missing severity, SP, identity, or duration rules create a visible exception; do not invent a penalizing rule.
- Each status visit is a separate episode. Exiting stops future accrual; returning creates a new episode. Existing penalties remain.
- Blocked/On Hold suspends the prior active episode's normal timer and resumes it with the accumulated eligible time when work resumes. Time blocked does not consume its allowance.
- Do not stack a normal delay deduction with a follow-up deduction for the same blocked interval.
- Each penalty is recorded once with a stable event identity. Re-importing or recalculating cannot duplicate it.
- Initial duration allowances must be entered by the admin; the earlier 3-SP/2-day example was illustrative, not an agreed production threshold.

## 11. Blocked / On Hold follow-ups

### Confirmed behavior

- Replace the normal duration timer with a shared follow-up timer.
- One comment from either the ticket's TPM or developer satisfies the requirement for both.
- Any comment by either responsible person qualifies; no mandatory content template.
- Accept comments from the CSV and manual portal entries.
- Follow-up interval: **3 working days**.
- First missed deadline deducts **2 points**; each additional overdue working day deducts **1 point**.
- Deduct from both developer and TPM when both are working; if only one is working, deduct only from that person; if both are off, deduct from neither.
- Values are editable by admins.

### Recommended shared-calendar calculation

Count a shared working day whenever at least one of the current developer or TPM is working according to their country calendar. Pause the shared clock only when both are off. Use a configured team timezone, default Asia/Amman, to identify shared dates; evaluate each person's country calendar on that date. Do not require overlapping office hours.

Start the clock on entry into Blocked/On Hold. Every qualifying comment starts a new follow-up interval. Once overdue, retain already-earned deductions; a comment prevents further deductions until the next breach. Attribute each deduction only to the owners who are working on its effective date. Show days counted and each person's eligibility in the explanation.

QA comments remain visible but do not reset this shared timer. Reassignment retains the shared deadline while changing future accountable owners. A later-imported qualifying comment must correct any penalties it proves should not have occurred, with an audit record.

## 12. CSV ingestion and evidence quality

### Confirmed requirements

Import a fresh CSV daily, preserve snapshots, compare changes, and use both CSV comments and manual comments. The prior discussion reported a sample containing 32 closed tickets and an encoded Time in Status field. That report is not a validated data contract: verify the actual CSV during implementation before relying on its encoding or historical precision.

### Recommended import process

1. Select a CSV and declare its export/snapshot time and project scope.
2. Detect encoding/delimiter, preview rows, and map columns using a reusable import profile.
3. Validate ticket keys, timestamps, assignees, statuses, priorities, SP, comments, and sprint fields.
4. Preview new tickets, changes, duplicates, unmapped values, and unavailable evidence.
5. Commit atomically, retaining original file, import metadata, row errors, and normalized records.
6. Recalculate affected timelines, delivery credits, and scoring events; show a result summary.

### Data contract and safeguards

- Required for a valid ticket row: Jira project/key and a recognized status. Missing assignee/SP may be accepted as flagged exceptions.
- Preferred fields: summary, issue type, priority, SP, assignee identity, created/updated/resolved dates, sprint, comments with author/time, and status/priority history when available.
- Resolve Jira identity primarily by stable account ID; permit explicit alias mapping when an export supplies names instead.
- Handle quoted multiline fields and repeated comment columns; do not deduplicate unrelated comments just because their text matches.
- Prefer Jira comment IDs for deduplication; otherwise use ticket, author, timestamp, and content hash, with ambiguous cases flagged.
- Exact duplicate files and snapshots are idempotent. Preserve evidence that an import was attempted without generating duplicate business events.
- An absent ticket in a later CSV is not deleted or marked Done; the export may be filtered.
- Out-of-order snapshots must not overwrite the latest observed state. Rebuild affected history in timestamp order.
- Same-time conflicting snapshots require a visible resolution choice; retain both source records.
- Aggregate Time in Status values are durations, not proof of a chronological sequence. Import verified duration totals separately unless a trustworthy decoder provides actual episodes.
- Where only snapshots exist, show status changes as observed between snapshots. Never claim exact transition times.
- Flag stale data prominently, including the latest snapshot date and missing import days. Calculations after the last observation are provisional and assume the last known state until new evidence arrives.
- Keep import warnings and calculation confidence visible in ticket detail and score explanations.

## 13. Manual follow-up entries and corrections

Recommended manual entry fields: ticket key, responsible author, comment text, occurrence timestamp, and optional Jira comment reference. The local operator records the entry on behalf of the named author; this is not an authenticated author action.

Allow editing/correction with an audit trail, including prior content, changed time, reason, and affected calculations. Link a later imported copy to the manual entry instead of counting the same comment twice. Manual overrides for ownership, timestamps, severity, SP, and score events require a reason and remain distinguishable from Jira evidence.

## 14. Dashboards and navigation

### Delivery / SP dashboard

- Completed SP by member, team, project, sprint, and selected period.
- Ticket count, SP by status, status age, expected versus actual working days by SP/severity, and overdue workload.
- Completion trends and workflow bottlenecks.
- Missing estimates and uncertain completion dates displayed separately.

### Developer utilization dashboard

- Weekly, monthly, quarterly, yearly, and custom period views.
- Delivered SP, target SP, utilization percentage, and monthly bonus progress.
- Individual and team comparisons, with developer count/target breakdown.
- Values above 100% remain visible rather than visually capped.

### Performance score dashboard

- Monthly baseline, each bonus category, each penalty category, and resulting score.
- Member, role, and team views.
- Multi-month average with links to the included monthly records.
- Provisional/final/revised status and data-quality flags.

### Ranking boards

Two distinct ranking dashboards are confirmed:

| Board | Individual scope | Role scope | Team metric |
| --- | --- | --- | --- |
| Utilization | Developers only | Developer only; QA/TPM shown as N/A | Total developer delivery / combined targets |
| Performance | Developers, QA, TPM | Filter/group by role | Average eligible member performance score |

Recommended ranking defaults: descending metric, shared rank for ties using unrounded values, name as display ordering within ties, visible period and population. Compare finalized periods by default and label live rankings provisional. No blended utilization/score ranking.

### Member profile

Clicking a name opens the selected year's twelve-month view of delivered SP, target, utilization where applicable, score, bonuses, deductions, team/country history, assigned tickets, and supporting event records. Ineligible months show N/A.

### Team profile

Show current and historical membership, utilization, average score, delivery, workflow distribution, overdue tickets, and shared follow-up risks. Every aggregate must expose the members, targets, and events that produced it.

### Recommended navigation

Overview; Delivery; Utilization; Performance; Rankings; Teams; Members; Tickets; Imports; Administration. Global filters include time period, project, sprint, team, member, role, severity, and status where applicable. Include local CSV exports of displayed reports.

## 15. Ticket lifecycle and detail

Confirmed: clicking any ticket from any dashboard opens its full available timeline.

The detail view contains:

- Jira key, title, original/current SP, severity, project, sprint, current status, and ownership.
- Status episodes with start/end evidence, working time, paused time, allowance, and overdue duration.
- Developer, QA, TPM, and team changes.
- Imported and manual comments, authors, timestamps, and source labels.
- Blocked/On Hold entries, follow-up resets, deadlines, missed follow-ups, and calendar explanations.
- Priority changes and the Critical reward window.
- Each penalty and bonus, recipient, effective date, formula, applicable rule version, and source evidence.
- First completion, SP credit, reopened events, and later completions without duplicate credit.
- Manual corrections, import references, uncertainty, and unresolved mappings.

Recommended timeline controls: chronological/reverse order, event-type filters, date filters, and expandable evidence. Distinguish exact timestamps from observed intervals and manually supplied dates. “Full lifecycle” means all available evidence, not fabricated pre-import history.

## 16. Administration

The local operator can configure:

1. Members, Jira identities/aliases, roles, countries, active dates, and historical team membership.
2. Teams, developers, primary/secondary QA, TPM, and shared-calendar timezone.
3. Countries, weekends, timezones, holiday dates/ranges, and effective dates.
4. Jira projects, import profiles, field mappings, status/priority mappings, and history decoders.
5. Workflows, status order/categories, role accountability, and terminal states.
6. Sprint/reporting periods.
7. Status/severity/SP duration rules, initial penalties, and daily increments.
8. Shared follow-up interval and deductions.
9. Monthly target, utilization bonus steps, Critical deadline, and score reward amounts.
10. Manual corrections, monthly recalculation, backup/restore, and exports.

Recommended change policy: new rules apply prospectively from an effective date. Record the rule version used by every calculation. Retroactive recalculation requires an explicit local action with a preview and reason; preserve revised monthly versions. This is a local audit action, not a login permission model.

## 17. Local data and operational requirements

Recommended persistent structure:

- One SQLite database for normalized data and calculation records.
- Local folders for original imports, backups, and report exports.
- Logical records for members, teams, membership periods, calendars, holidays, workflows, statuses, rules/versions, sprints, imports, snapshots, tickets, ownership episodes, status episodes, comments, follow-up intervals, delivery credits, score events, monthly summaries, and corrections.
- Preserve source evidence and derived calculations separately so calculations can be explained and rebuilt.
- Use transactions for imports and corrections. A failed import must not leave a partial scoring state.
- Enforce unique first-delivery credit per Jira ticket and unique calculation-event keys.
- Refresh calculations on startup, after imports/corrections, and on dashboard refresh. The computer need not remain running to preserve deadlines.
- Produce a consistent database backup using SQLite's backup mechanism before major imports or recalculation. Back up associated original imports with a manifest. Provide manual backup/restore; retain 30 automatic backups by default.
- Restore into a validated copy before replacing the active dataset.
- Keep application assets local and avoid runtime dependence on remote fonts, analytics, or CDNs.
- Preserve data across application restarts; retain business history indefinitely unless explicitly removed by the operator.

## 18. Worked examples

### Delivery and monthly utilization

A developer completes 20 original SP in a month. Utilization is 20 / 16 × 100 = **125%**. One full 20% increment above 100 earns **+10 score points**. With one qualifying Critical reward and 3 penalty points, monthly score is 100 + 10 + 1 − 3 = **108**.

### Blocked follow-up

A shared follow-up crosses its 3-working-day allowance without a qualifying comment. Both people are working at the breach: each receives −2. After one additional shared working day, only the TPM is working: the TPM receives −1 and the developer receives none. A comment by either resets the deadline without erasing valid earlier deductions.

### Reopening

A 5-SP ticket first reaches Done in January, is reopened in February, and reaches Done again in March. January retains 5 SP; February loses none; March earns no duplicate SP or Critical completion reward.

### Team and quarter

Three developers active for a full month deliver 60 SP. Team utilization is 60 / (16 × 3) × 100 = **125%**. A developer delivering 54 SP over a full quarter has 54 / 48 × 100 = **112.5%** utilization. Monthly scores of 100, 110, and 105 produce a quarterly score of **105**, with no additional quarterly utilization bonus.

## 19. Acceptance criteria

1. The application runs on the owner's computer without login and persists data in a local SQLite file.
2. Re-importing identical data changes neither delivery credits nor score events.
3. Each committed import retains a snapshot and source evidence; missing tickets are not automatically closed.
4. Only the first credited Done completion contributes original SP; reopening never reverses or duplicates it.
5. Monthly, quarterly, annual, and prorated weekly targets follow the specified formulas.
6. Country-specific weekends and holidays pause applicable timers; shared follow-up eligibility follows the specified both-off rule.
7. QA delays can deduct from the developer, both QAs, and TPM; Ready for Release excludes the developer.
8. Blocked/On Hold intervals produce follow-up penalties only, and a qualifying TPM/Dev comment resets their deadline.
9. Configurable status/severity/SP rules determine deadlines and deductions, with missing rules explicitly flagged.
10. Monthly utilization bonuses use full 20% steps and do not repeat in longer-period reports.
11. A verified Critical-to-Done completion within the configured window awards +1 score point to each eligible owner once.
12. Multi-month scores average eligible monthly scores; utilization uses total delivered SP divided by the period target.
13. QA/TPM appear in score rankings and have no fabricated utilization value.
14. Clicking a person opens yearly monthly history; clicking a ticket opens all available lifecycle evidence.
15. Every score and ranking can be traced to source tickets, events, owners, calendars, and rule versions.
16. Corrections preserve an audit trail and update affected monthly records without silently overwriting prior versions.
17. Backup and restore preserve the complete usable dataset.
18. Branding is supplied before interface design begins.

## 20. Delivery sequence

1. Validate the CSV's actual fields/history and establish import mappings against the confirmed Optimum Partners identity.
2. Build the local database, configuration, team/member setup, and country calendars.
3. Implement transactional daily imports, snapshots, evidence flags, and ticket lifecycle.
4. Implement working-time, ownership, delivery, follow-up, bonus, and deduction calculations.
5. Build delivery, utilization, performance, rankings, member, and team views.
6. Validate worked examples and acceptance scenarios; add local export and backup/restore.

This document describes required business behavior, not a claim that every implementation or platform check is complete. Missing historical source evidence must remain an explicit exception rather than an inferred fact.

## 21. Subsequent confirmed decisions

- Use Start date and End date pickers instead of a month-only selector, allowing combined months and quarters. Preserve monthly bonus calculation and monthly score averaging.
- Provide country filters and show each developer's country in tables and profiles.
- Provide interactive Chart.js dashboards and a yearly per-person dashboard with monthly drill-down.
- Determine ticket teams automatically from Jira assignee/member mappings; no per-file team assignment is required.
- Daily imports update existing tickets by Jira key and append new evidence without overwriting prior snapshots or duplicating comments.
- Keep the application local and without login. The publicly shared sample-data design preview is separate from the local database application.
- Do not add CI workflows. Tests are run locally.
- Source repository: https://github.com/diabalsadi/op-tracker
