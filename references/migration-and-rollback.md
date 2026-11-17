# Data migration, validation, cutover and rollback

Use this for every proposal that moves or copies data into new tables (Phase 4). Contents: 1 Principles, 2 Find every writer, 3 Backfill, 4 Keeping old and new in sync, 5 Validation, 6 Cutover runbook, 7 Rollback, 8 Cleanup, 9 What to write in the plan.

## 1. Principles

- The old tables and old service stay untouched and keep working. The new tables hold **copies** until cutover.
- Everything is idempotent and restartable: running a script twice must not duplicate or corrupt data.
- Both old and new tables live in the same database, so one `SaveChanges` or one transaction can write to both atomically. This is the main reason dual-write is usually the right sync strategy here.
- Progress through environments (dev, test, staging, production), with the same runbook each time.
- Nothing is dropped in this plan. Old objects are removed only in a separate cleanup the user approves after a stable period.

## 2. Find every writer first

Drift between old and new data comes from any write that does not go through the new path. From the audit, list **every workflow that writes the old table** (INSERT, UPDATE, DELETE, bulk, raw SQL, stored procedures, background jobs, migrations that move data) and add a row for each in the proposal. Also ask whether anything outside this repo writes to it (other services, ETL, SQL Agent or Azure jobs, manual scripts, BI tools).

For each writer decide: route through the new dual-write service, or cover by delta sync or trigger, or park the proposal because an outside writer cannot be controlled.

## 3. Backfill (initial copy)

- Copy in **batches** by clustered key range (keyset paging: `WHERE Id > @last ORDER BY Id` with `TOP (@batch)`), not by `OFFSET`.
- Batch size 1,000 to 10,000 rows, tuned so each batch commits quickly and the transaction log stays small. On Azure SQL watch log rate and DTU/vCore limits; add a short `WAITFOR DELAY` between batches if needed.
- Idempotent insert: `INSERT ... SELECT ... WHERE NOT EXISTS (SELECT 1 FROM New n WHERE n.Id = o.Id)`, or `MERGE` where appropriate (be aware of `MERGE` caveats; prefer `INSERT`/`UPDATE` pairs).
- Run off-peak. Record start/end, rows copied, and the last key reached so it can resume.
- Deliver as a SQL script or a one-off console/Hangfire job under a flag. The plan names which; the implementation step writes it.

## 4. Keeping old and new in sync until cutover

Pick one per table, with reasons.

- **Dual-write in the new service (default).** The new service writes old and new tables in one transaction. Old data stays authoritative until cutover; the new service is exercised only for the portion of traffic or environments chosen by the flag. Because the old service also keeps writing old tables, any write by the old service must reach the new tables too: either the old path is replaced by the new service for writes first, or delta sync covers it.
- **Delta sync job.** A repeating job copies rows changed since the last run, using a `rowversion` column, a `ModifiedAt` column that is reliably maintained, or SQL Server change tracking. Note that enabling change tracking is a database setting change that needs approval. Good for tables with outside writers; adds lag.
- **Triggers on the old table** that mirror changes into new tables. Easiest to guarantee coverage, but they add write cost and hide logic in the database; use sparingly and state the cost.
- **Temporal tables** are an option when history is also wanted, but they change an existing table, so they conflict with the "do not alter existing tables" rule; park unless the user approves.

Failure handling: define what happens if a dual-write fails (the transaction rolls back both; the request fails the same way it did before) and how a delta job retries.

## 5. Validation

Run these before cutover and again after it:

- **Counts:** row counts old vs new (adjusted for archive rules).
- **Anti-joins:** rows in old missing in new, and new rows with no old counterpart.
- **Content comparison per key range:** compare `CHECKSUM_AGG(BINARY_CHECKSUM(cols))` or `HASHBYTES` over the same columns in both, batch by batch, and drill into mismatching ranges.
- **Shadow reads (recommended for high-risk proposals):** on live or replayed requests, the new service runs behind the scenes, its result is compared to the old service's result, and differences are logged without affecting the response. Switch only after differences reach an agreed level (ideally none).
- **Contract tests:** the controller responses for the covered workflows are identical (status code, body, ordering, paging) between old and new services, using characterization tests recorded against the old path.
- **Performance check:** the target queries are measured before and after (Query Store or timings) so the benefit moves from `estimated` to `measured`.

## 6. Cutover runbook

1. Preconditions: backfill complete, validation clean, sync healthy, rollback rehearsed in a lower environment, owners and window agreed.
2. Final delta sync (or pause writers briefly if needed).
3. Flip the flag for the new service (per environment, then gradually in production if the flag supports a percentage or tenant).
4. Watch: error rate, latency, validation job, shadow-read diffs, DB resource use, for the agreed observation period.
5. Keep dual-write on after cutover (see rollback).

## 7. Rollback

- **Before cutover:** nothing to roll back; stop the sync and the new tables are ignored. Remove them with the migration's `Down()` if desired.
- **After cutover:** flip the flag back to the old service. This is only lossless if writes during the new-service period were also applied to the old tables, so **keep dual-write running for an agreed period after cutover**. State that period in the plan.
- **Point of no return:** define it explicitly. It is the moment dual-write is turned off (so old tables go stale), or old tables are dropped. Do not reach it until the stability period has passed and the user approves.
- **Schema rollback:** each additive migration has a `Down()` that drops only the new objects. Dropping new tables loses only copied data, which can be backfilled again.
- Rehearse rollback in a lower environment and record the result.

## 8. Cleanup (separate, later)

After a stable period: turn off dual-write, archive then remove old tables or columns, remove old services and flags, and remove the extra sync jobs. This is its own plan item, needs explicit approval, and is out of scope for the first rollout.

## 9. What to write in the plan (per proposal)

One row in the migration table (Backfill, Sync strategy, Validation, Cutover, Rollback, Point of no return), plus a short detail section listing the writers of the old table and how each is covered, batch size, estimated copy duration and log impact if known, and the rehearsal evidence required before production.
