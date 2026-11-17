---
name: db-optimization-plan
description: Turns a database usage audit (the CSV, Excel or markdown report from the db-usage-audit skill) plus the backend code into a safe, reviewable DB optimization plan for a .NET / EF Core code-first + SQL Server application. Proposes index changes, table splits, normalization, stored procedures and service-level query fixes, each with evidence, new-model and new-service design, data migration, validation, cutover and rollback, and groups the work into non-overlapping work packages that different developers or coding agents can take in parallel. Hard rules - controllers, routes and request/response contracts never change, existing models, tables and services are never edited (new ones are added behind a switch), so the old behavior stays available for rollback. Plan only, no code changes. Output is a markdown plan plus Excel and CSV files. Use this whenever the user wants to optimize or restructure their database using an existing usage report, decide which tables to split or index, plan data migration to new tables, or split DB optimization work across people or agents, even if they never say "plan" or "skill".
---

# DB Optimization Plan (.NET 8 / EF Core code-first / SQL Server)

## Purpose

Take the factual DB usage audit and decide **what to change, in what order, how to migrate the data safely, and how to divide the work** so several developers or agents can proceed without colliding. The output is a plan a human reviews and approves item by item. Nothing is implemented here, because a plan that can be reviewed and rejected cheaply is what keeps a database change safe.

## Hard constraints (apply to every proposal)

These come from how the team wants to work. Check each proposal against them, and **park** (do not force) any proposal that cannot satisfy them, saying what would unblock it.

1. **API contract is frozen.** Controllers, routes, request and response DTOs, status codes and validation behavior do not change. Only the service, repository and data-access layers change. Controllers appear in the plan as "unchanged, read-only".
2. **Existing code is immutable.** Existing entities, `DbContext` configuration, tables, services, repositories and migrations are not edited. Add **new** entities, configurations, services and additive EF migrations. Reason: if anything goes wrong the old path is still intact, so rollback means flipping a switch, not reverting a refactor.
3. **New behind a switch.** The new service is selected by a feature flag or DI registration so the old service can be restored by configuration alone. The controller keeps calling the same interface.
4. **Additive schema only.** New tables, new indexes, new procedures. No dropping or altering existing tables in this plan (old objects are removed only in an explicit, later cleanup phase the user approves).
5. **Every proposal ships with** a data-migration approach (if data moves), validation, cutover, and a tested rollback.

One deliberate exception: **new indexes on existing tables** and **stored procedures** change the database, not the C# models. Propose them as raw-SQL migrations (`migrationBuilder.Sql`) so entity and configuration files stay untouched. Say so in the proposal. Details in `references/proposal-patterns.md`.

## What the agent needs (works in any AI coding tool)

Plain markdown plus two helper scripts. It runs in Claude Code, GitHub Copilot (agent mode), Cursor (agent mode), Windsurf, Codex-style CLIs and similar, as long as the agent can read and search the repo, create files, and run shell commands (optional; see preflight fallbacks). Chat-only modes are not enough.

`<skill-dir>` means the folder containing this file. Read the files in `references/` when a phase points to them.

Every phase saves its result to `.db-plan-work/`, so a tool with a small context window can work one area at a time and resume after a reset.

## Output

- `DB_OPTIMIZATION_PLAN.md`, following `references/plan-template.md` (headers must stay verbatim so the export works)
- `DB_OPTIMIZATION_PLAN.xlsx` and one CSV per sheet in `DB_OPTIMIZATION_PLAN_csv/`, produced from the markdown by `scripts/build_plan_outputs.py`

## Phase -1: Preflight

Find Python 3.8+ (`python3`, `python`, `py -3`) and call it `<py>`. The CSV export needs only the standard library. For `.xlsx`, check `<py> -c "import openpyxl"` and, if missing, run `<py> -m pip install --user openpyxl` without asking. If Python is missing, offer the platform install command and run it only if the user says yes; otherwise do the analysis by hand from the audit file (read it, group in your head and in `.db-plan-work/` notes) and write the CSVs directly. Mention what you did in the final message.

## Phase 0: Intake

1. Locate the audit output the user points to: `DB_USAGE_REPORT.md`, `.xlsx`, or CSV files. Read its header: the completeness gate result, the number of unresolved items, and the stack summary.
2. If the gate failed or many items are unresolved, say which tables or workflows the plan cannot cover reliably, and list them in the plan's assumptions. Do not silently plan around gaps.
3. Ask the user once (and continue without waiting if they do not have it) for runtime data from Azure: Query Store top queries by duration/CPU/executions, `sys.dm_db_index_usage_stats`, missing-index DMVs, table sizes and row counts, and any known slow endpoints. Never connect to a database yourself. If runtime data is absent, mark every benefit **unmeasured** and prefer low-risk, evidence-backed items first.
4. Record environment facts that change advice: Azure SQL tier, whether other apps or jobs write to the same tables, deployment model (zero-downtime or windows).

## Phase 1: Profile the audit

Run:

```
<py> <skill-dir>/scripts/analyze_audit.py <audit.csv or folder> --out .db-plan-work/profile.json
```

It normalizes flat or wide audit CSVs and computes, per table: which workflows read, write, filter, join and sort it; column groups used by identical workflow sets (raw material for splits); unindexed filter/join/sort columns; hub tables; and connected groups of tables (which drive work packages). It prints a summary and tells you if it could not map the CSV headers; in that case map the columns by hand (see `--help`) and re-run.

The script is a starting point. Read `profile.json`, then **verify the top candidates against the real code**: open the service or repository for each workflow behind a proposal. The audit is static and may have gaps; a plan built on a wrong trace is worse than no plan.

## Phase 2: Find candidates

Use `references/proposal-patterns.md`. Look for, in this order of safety:

1. Missing or poorly shaped **indexes** for NOT-COVERED / PARTIAL predicates, and indexes that duplicate or overlap.
2. **Service-level query fixes** in the new service (projection instead of whole entities, no N+1, paging, targeted updates instead of `Update()` writing all columns).
3. **Stored procedures** for chatty multi-step workflows or bulk set-based work.
4. **Table splits and normalization** (hot/cold columns, columns used by disjoint workflows, large or delimited/JSON columns that get filtered).
5. Anything else the evidence supports.

Every candidate cites evidence IDs from the audit (`W-xxx`, `T-xxx`, `IX-xxx`) and, once runtime data exists, the measurement. A proposal with no evidence is not a proposal.

Do not propose removing an index or column based on static data alone. "No traced workflow uses it" is a reason to check Query Store, not a reason to drop.

## Phase 3: Constraint check

Run each candidate against the hard constraints above. Record pass/park. For each park, write the reason and what would unblock it (for example "needs a response shape change" or "other application writes this table; needs its owner's agreement").

## Phase 4: Design each accepted proposal

For each, write (see `references/plan-template.md` for the exact layout):

- the change (DDL sketch, or the query or procedure shape),
- **new** entities, configurations, service and repository names, and the interface the controller already depends on (the new service implements the same interface or sits behind an adapter),
- code impact: existing files that are read-only references, new files to create, and the rare existing file that must change (flag these as conflict risks; normally only DI registration and configuration),
- data migration, validation, cutover and rollback per `references/migration-and-rollback.md`, enumerating **every writer of the old table** from the audit, since any writer that bypasses the new path will let old and new data drift,
- tests that prove the response is identical to the old service's (contract or characterization tests),
- benefit (with confidence: `measured`, `estimated`, `unmeasured`), risk, effort.

## Phase 5: Work packages (parallel-safe split)

Follow `references/work-packages.md`. Group proposals into packages by functionality so each developer or agent owns a distinct area:

- packages derive from connected table groups and workflows in `profile.json`; proposals touching the same table or service go in one package,
- list for each package the affected controllers (unchanged), existing services and repositories (read-only references), new files to create, and the few existing files that need edits,
- assign every shared hotspot (EF `ModelSnapshot`, migrations folder, `DbContext`, DI registration, shared base classes and mappers, test fixtures, configuration) to a single owner package, usually a foundation/integration package,
- order packages by dependency and give a merge order, with migrations generated in sequence by the integration owner,
- write a short task brief per package that can be handed to a developer or agent as is.

## Phase 6: Write outputs and verify

1. Write `DB_OPTIMIZATION_PLAN.md` from the template.
2. Run:

```
<py> <skill-dir>/scripts/build_plan_outputs.py DB_OPTIMIZATION_PLAN.md --out DB_OPTIMIZATION_PLAN
```

It writes the CSVs (always) and the `.xlsx` (if openpyxl is available), and checks for a file owned by two packages, proposals not assigned to any package, and packages that list controllers as changed. Fix the plan and re-run until it reports no conflicts.
3. Completeness gate, reported at the top of the plan: every proposal cites evidence, has migration/rollback and a test, belongs to exactly one package; no file is owned by two packages; every controller is "unchanged"; parked items have reasons; assumptions and unmeasured items are listed.
4. Final message: where the files are, the counts (proposals, packages, parked), the biggest unmeasured assumptions, and which Azure data to collect to firm them up.

## Quality rules

- Plan only. Do not edit application code, create migrations, or touch the database.
- Evidence and IDs everywhere, so reviewers can trace a proposal back to the audit.
- State confidence and what is unmeasured. Prefer smaller, reversible steps and say why.
- Keep benefit claims modest; do not quote percentages without measurements.
- Keep tables machine-friendly: consistent headers, one row per fact, file lists separated by `;`.
