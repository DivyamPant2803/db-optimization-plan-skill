# db-optimization-plan

An AI coding agent skill (Claude Code, GitHub Copilot, Cursor, Windsurf, Cline, Codex-style CLIs) that turns a **database usage audit** into a safe **DB optimization plan** for a **.NET / EF Core (code-first) + SQL Server** backend.

It is the second step after [`db-usage-audit`](https://github.com/DivyamPant2803/db-usage-audit-skill): the audit records which workflows touch which tables, columns and indexes; this skill decides what to change and how to roll it out.

**Plan only.** It does not edit your code, create migrations or touch a database. You review the plan and approve items before anything is implemented.

## What it produces

| File | Purpose |
|---|---|
| `DB_OPTIMIZATION_PLAN.md` | The full plan, for review and for handing to agents |
| `DB_OPTIMIZATION_PLAN.xlsx` | The plan's tables as sheets you can filter and sort |
| `DB_OPTIMIZATION_PLAN_csv/*.csv` | The same sheets as CSV (always written, no extra install needed) |

Sheets: `Proposals`, `Migration_Plan`, `Work_Packages`, `Shared_Files`, `File_Overlap`, `Package_Overlap`, `Parked`, `Issues`.

## The rules it plans within

1. **API contract frozen.** Controllers, routes and request/response DTOs never change. Only service, repository and data-access code does.
2. **Existing code and tables are never edited.** New entities, configurations, services and additive EF migrations only, so the old behavior stays intact for rollback.
3. **New behind a switch.** A feature flag or DI registration chooses old or new service; rollback is flipping it back.
4. **Additive schema only.** No dropping or altering existing tables in the plan. Cleanup is a separate, later, approved step.
5. **Every proposal** includes data migration (if data moves), validation, cutover and a rollback.

Index and stored-procedure proposals change the database but not the C# models, so they are delivered as raw-SQL migrations.

## What the plan contains

- **Proposals:** index changes, service-level query fixes, stored procedures, table splits, normalization, archiving, each with audit evidence, new-model and new-service design, risk, effort and benefit (marked measured / estimated / unmeasured).
- **Migration plan per proposal:** batched backfill, how old and new data stay in sync (dual-write by default, delta sync or triggers when outside writers exist), validation, cutover runbook, rollback and the point of no return. It enumerates **every writer** of the old table from the audit, since any writer that bypasses the new path causes drift.
- **Work packages by functionality**, so different developers or agents can work in parallel: affected controllers (read-only), existing services referenced, new files to create, files that must change, dependencies, waves and merge order. Shared hotspots (EF `ModelSnapshot`, migrations, `DbContext`, DI registration, shared base classes, test fixtures) are owned by one foundation package. Each package has a task brief ready to hand off.
- **Parked proposals** that cannot meet the rules, with the reason and what would unblock them.
- A **checker** that flags a file owned by two packages, a controller listed as modified, and proposals without evidence, package or migration row.

## Install

```bash
git clone <this-repo-url> db-optimization-plan
cd db-optimization-plan
python3 install.py --target /path/to/your-backend-repo --tool copilot
```

Replace `copilot` with `cursor`, `claude`, `windsurf`, `cline`, `agents` or `all` (repeat `--tool` for several). The installer copies the skill into your project and writes the pointer file each tool uses:

| `--tool` | Creates | Run it with |
|---|---|---|
| `claude` | `.claude/skills/db-optimization-plan/` | Ask in Claude Code, or `/db-optimization-plan` |
| `cursor` | `.cursor/rules/db-optimization-plan.mdc` + `.db-optimization-plan/` | Cursor Agent mode |
| `copilot` | `.github/prompts/db-optimization-plan.prompt.md` + `.db-optimization-plan/` | Copilot Chat Agent mode, `/db-optimization-plan` |
| `windsurf` | `.windsurf/rules/db-optimization-plan.md` + `.db-optimization-plan/` | Cascade picks it up |
| `cline` | `.clinerules/db-optimization-plan.md` + `.db-optimization-plan/` | Ask Cline |
| `agents` | a section in `AGENTS.md` + `.db-optimization-plan/` | Codex, Gemini CLI, other `AGENTS.md` tools |

Safe to re-run; hand-written files are not overwritten unless you pass `--force`. If `git clone` is not possible, download the repo as a ZIP from GitHub and run the same command. For any other tool, copy `SKILL.md`, `references/` and `scripts/` to `.db-optimization-plan/` and tell the agent: *"Follow the instructions in `.db-optimization-plan/SKILL.md` exactly."*

The adapter file formats follow each tool's documented conventions; only the installer's output and idempotence were tested here, not each IDE.

### Requirements

- An AI coding tool in **agent mode** (read and search the repo, create files, run shell commands).
- The audit output from `db-usage-audit` (CSV, Excel or markdown).
- Python 3.8+ for the two helper scripts. The skill's preflight finds Python and installs `openpyxl` itself (user-level). Without Python it works by hand from the audit and writes CSVs directly. `.xlsx` needs `openpyxl`; CSV never does.

## How to use

1. Install the skill into your backend repo (see Install) and put your audit output where the agent can read it.
2. Open your AI tool in **agent mode** in that repo.
3. Paste prompt **1** from [Prompts to copy](#prompts-to-copy) below, filling in the audit path. It produces the plan, the Excel file and the CSVs.
4. Review the plan, then give each approved work package to a developer or agent with prompt **4** (and prompt **5** for the foundation package).

## Prompts to copy

`SKILL.md` holds the instructions the agent follows once the skill is loaded. These are the prompts you type. Replace the `<...>` placeholders. They work in any tool in agent mode; if your tool does not pick the skill up by itself, start with: "Follow the instructions in `.db-optimization-plan/SKILL.md` exactly."

### 1. Generate the plan (main prompt)

```text
Follow the db-optimization-plan skill (.db-optimization-plan/SKILL.md) for this repository.

Input: the DB usage audit at <path to audit CSV, folder of CSVs, xlsx or DB_USAGE_REPORT.md>.
Runtime data (optional): <paths to Query Store / index usage / table size exports, or "none">.

Goal: propose how to optimize our SQL Server database (indexes, table splits, normalization,
stored procedures, service-level query fixes) based on the audit and the real code.

Hard rules:
- Plan only. Do not change code, create migrations or touch any database.
- Do not change controllers, routes or request/response DTOs.
- Do not edit existing entities, DbContext configuration, tables, services or migrations.
  Add new entities, configurations, services and additive EF migrations behind a feature flag
  so we can roll back by switching back to the old service.
- Every proposal needs: audit evidence, new-model and new-service design, data migration
  (batched backfill, how old and new stay in sync, validation, cutover), rollback, tests that
  prove responses are unchanged, and risk/effort/benefit (marked measured, estimated or unmeasured).
- List every writer of each old table and say how each is covered.
- Park anything that cannot follow these rules, with the reason and what would unblock it.
- Split the work into packages by functionality for different developers or agents, with no file
  owned by two packages. Give each package its affected controllers (read-only), existing services
  (read-only), new files, files that must change, dependencies, merge order and a task brief.
  Put shared files (ModelSnapshot, migrations, DbContext, DI registration, shared base classes,
  test fixtures) in one foundation package.

Output: DB_OPTIMIZATION_PLAN.md, DB_OPTIMIZATION_PLAN.xlsx and DB_OPTIMIZATION_PLAN_csv/ in the repo root.
Run the build_plan_outputs.py check and fix every error before you finish. Verify the top candidates
against the actual code, and tell me what is unmeasured and which Azure data would firm it up.
```

### 2. Narrow the scope

```text
Follow the db-optimization-plan skill, but only for the <Orders, OrderLines> tables and the workflows
that touch them. Start with index and service-level query fixes; do not propose table splits yet.
Keep all the hard rules and produce the same outputs.
```

### 3. Review or revise an existing plan

```text
Open DB_OPTIMIZATION_PLAN.md. Challenge it against the code: for each accepted proposal check that the
cited workflows really use those columns, that every writer of the old table is covered, that no controller
or existing file changes, and that no file appears in two packages. Report problems, fix the plan,
and re-run build_plan_outputs.py until it reports no errors. Do not implement anything.
```

### 4. Hand a work package to a developer or coding agent (implementation)

Give each approved package to a different person or agent, one at a time. This prompt is self-contained, so the implementing agent does not need the planning skill. Paste the package's task brief from section 7 of the plan where indicated.

```text
Implement work package <PKG-03> from DB_OPTIMIZATION_PLAN.md. The task brief is:

<paste the package's task brief>

Rules:
- Only create or edit the files listed for this package. Do not touch controllers, existing services,
  existing entities, existing migrations, or any shared file owned by another package.
- Keep the API unchanged: the new service implements the same interface and returns identical responses.
- Put the new service behind the feature flag <flag name>; it must default to the OLD service.
- Do not generate EF migrations or edit the ModelSnapshot; the foundation package owns those. Write entities,
  configurations, services, tests, and the data migration/backfill and validation scripts described in the plan.
- Write contract/characterization tests that prove the new service returns the same results as the old one,
  and validation checks for the data migration (counts, anti-joins, checksums).
- Do not run anything against a production database.
When finished, list the files you changed, the tests you ran and their results, and anything in the plan
that turned out to be wrong or missing.
```

### 5. Foundation package (migrations, feature flags, DI)

```text
Implement PKG-00 (foundation) from DB_OPTIMIZATION_PLAN.md: feature flag infrastructure, DI registration for
the new services behind their flags, and the EF migrations for the other packages in the merge order given
in section 6 of the plan. Only additive migrations; every Down() must drop only new objects. Index and
stored-procedure changes go in raw-SQL migrations. Do not modify existing entities or configurations.
```

### 6. Rebuild the Excel and CSV only

```text
Run scripts/build_plan_outputs.py on DB_OPTIMIZATION_PLAN.md to regenerate DB_OPTIMIZATION_PLAN.xlsx and the
CSV files, and report any errors it finds.
```

## Get better plans: bring Azure runtime data

The audit is static, so it knows which workflows touch which columns but not how often. Give the agent, if you can, exports of Query Store top queries (duration, CPU, executions), `sys.dm_db_index_usage_stats`, table sizes and row counts. Without them every benefit is marked **unmeasured** and the plan favors low-risk, evidence-backed items first. The agent never connects to your database.

## After the plan

1. Review proposals, the migration rows and the parked list. Approve or reject items.
2. Hand each approved package's task brief to a developer or agent. Packages are designed not to share files; the foundation package owns the shared files and generates migrations in merge order.
3. Rehearse cutover and rollback in a lower environment before production.

## Limits

- Static analysis of the audit plus code reading. Benefits are not guaranteed without measurements.
- File lists per package come from audit traces and code reading; hidden shared helpers can be missed. Run the plan's `File_Overlap` check and a repo search before assigning work.
- Parallel packages reduce conflicts but do not remove them; the foundation package and merge order matter.
- Built for .NET, EF Core and SQL Server.

## Layout

```text
SKILL.md                                    The skill: phases, hard rules, quality gate
references/proposal-patterns.md             Index, query-fix, stored-procedure, split patterns for SQL Server/EF
references/migration-and-rollback.md        Backfill, sync, validation, cutover, rollback
references/work-packages.md                 How to split work; EF shared hotspots; task brief template
references/plan-template.md                 Exact plan layout (the export depends on its headers)
scripts/analyze_audit.py                    Profiles the audit CSV (hubs, split candidates, unindexed predicates, table groups)
scripts/build_plan_outputs.py               Plan markdown -> .xlsx + CSVs, and plan checks
install.py                                  Installs into a project for Claude, Cursor, Copilot, Windsurf, Cline, AGENTS.md
```
