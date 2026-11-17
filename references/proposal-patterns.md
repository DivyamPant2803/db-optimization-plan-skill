# Proposal patterns (SQL Server / EF Core)

Use this when finding and shaping candidates (Phase 2) and designing them (Phase 4). Contents: 1 Indexes, 2 Service-level query fixes, 3 Stored procedures, 4 Table splits and normalization, 5 Other options, 6 Rejecting or parking, 7 Sizing benefit and risk.

Every proposal must keep the constraints: API contract frozen, existing code immutable, new behind a switch, additive schema.

## 1. Indexes

Lowest risk, often highest value. No model change needed.

When to propose:
- A filter, join or sort column in the audit is `NOT-COVERED` or `COVERED-PARTIAL` and the workflow is user-facing or frequent.
- Foreign key columns used in joins with no index (EF creates FK indexes by convention, but not for all configurations; check the audit's index list).
- Two indexes where one is a left-prefix of the other (overlap), or an index no query can use (confirm with usage stats first).

Shaping rules:
- Key order: equality columns first, then range column, then sort columns that match the `ORDER BY`. Put the most selective equality column first when the order among equalities is free.
- `INCLUDE` columns to cover a hot read that otherwise does key lookups, if the included columns are few and narrow. Avoid including `nvarchar(max)`.
- Filtered index for a constant predicate such as the soft-delete filter (`WHERE IsDeleted = 0`). The query predicate must match the filter exactly; EF's global query filter usually produces a compatible predicate, but verify.
- Key size limit: 900 bytes clustered, 1700 bytes nonclustered. Avoid wide `nvarchar` keys.
- Every index adds cost to every INSERT/UPDATE/DELETE. For tables the audit shows are written by many workflows, say what write cost is added and keep the number of new indexes small.
- Predicates that stay non-sargable (function on the column, leading wildcard `LIKE '%x'`, implicit conversion) are not fixed by an index. Propose the service-level fix (section 2) instead or as well.
- Build on Azure SQL with `ONLINE = ON` (and `RESUMABLE = ON` for large tables where supported) so it does not block writers. Schedule off-peak and state the expected log and IO impact.

How to deliver without touching entities: a migration whose `Up()` runs `migrationBuilder.Sql("CREATE NONCLUSTERED INDEX ... WITH (ONLINE = ON)")` and `Down()` drops it. State that the index is intentionally absent from the EF model, so future EF-generated migrations will not remove it, and note it in team docs.

Removal proposals: only with usage stats over a representative period (`sys.dm_db_index_usage_stats` resets on restart) and a check that no raw SQL, report, job or other application depends on it. Park otherwise.

## 2. Service-level query fixes (in the new service)

The new service replaces the old one behind the switch, so fix the data access there and leave the old service as is.

- Project to the response shape with `Select` instead of materializing whole entities when the audit shows `*` reads but the response uses few columns.
- Remove N+1: load related data in one query (`Include` with `AsSplitQuery()` where cartesian explosion is a risk), or project.
- Add `AsNoTracking()` on read paths.
- Page unbounded lists. Careful: paging must not change the response contract. If the API returns everything today, keep returning everything and park the paging idea with the reason.
- Replace `Update(entity)` (writes every column) with targeted updates: modify only changed properties on a tracked entity, or `ExecuteUpdate` for set-based changes.
- Batch writes into one `SaveChanges` where the audit shows `SaveChanges` per row in a loop.
- Make predicates sargable: compare dates by range instead of `.Date`, avoid `.ToLower()` on columns (use a case-insensitive collation or a computed, indexed column), avoid leading wildcards.
- Keep behavior identical: same ordering, same nulls, same errors. Characterization tests prove it.

## 3. Stored procedures

Propose when:
- A workflow makes several dependent round trips (read, decide, write) that can run as one set-based unit.
- Bulk updates or deletes are done row by row from C#.
- A reporting query's EF translation is poor and cannot be fixed with LINQ.

Do not propose for simple CRUD. Costs to state: logic moves out of C#, versioning and testing are harder, parameter sniffing risk, and DB deployment must keep procedures in migrations.

Delivery: `migrationBuilder.Sql("CREATE OR ALTER PROCEDURE ...")` with `Down()` dropping it; schema-qualify names; `SET NOCOUNT ON`; explicit parameter types and lengths. The new service calls it with `FromSqlInterpolated` / `ExecuteSqlInterpolated` or ADO.NET. Keep transaction scope explicit.

## 4. Table splits and normalization

Evidence to look for in `profile.json`:
- **Disjoint column groups:** columns in one table used by different, non-overlapping workflow sets. Hot columns read on every list view vs cold columns read only on detail pages.
- **Wide or LOB columns** (`nvarchar(max)`, `varbinary(max)`, JSON blobs) pulled by `*` reads that do not need them.
- **Hot write columns** (counters, status, last-seen timestamps, version fields) in a table that is otherwise read-mostly: updates cause locking, page splits and cache churn.
- **Delimited or JSON columns that are filtered on:** normalize into a child table so the filter can use an index.
- **Very large append-only tables** read mostly by recent rows: consider an archive/history table (horizontal split).
- **Optional 1:1 data** that is NULL for most rows.

Design rules for the plan:
- New tables, new entities, new configurations. The existing table and entity stay exactly as they are and remain the source of truth until cutover.
- Vertical splits use a shared primary key (1:1 extension tables). Foreign keys exist only between new tables, never from new tables into old tables (so rollback and cleanup stay simple).
- The new service implements the same interface as the old service (or sits behind an adapter) and returns the same DTOs.
- Name new things with a clear, consistent prefix or suffix so reviewers can tell old from new.
- Do not split just because a table is wide. If every workflow uses the same columns together, a split adds joins and no benefit; say so and leave it.
- Partitioning mainly helps manageability (switching, archiving) more than query speed on Azure SQL; propose only with a clear maintenance reason.

## 5. Other options

- **Data compression** (`ROW` or `PAGE`) on large, read-heavy tables: changes physical storage, not schema, and can be reversed with a rebuild. Flag it as touching an existing table's storage and needing approval.
- **Columnstore** for analytic read workloads on large tables.
- **Data type right-sizing** (for example `nvarchar` to `varchar`, `datetime` to `datetime2(0)`): alters existing columns, so it only fits new tables in this plan; otherwise park.
- **Caching** at the service layer for reference data the audit shows is read often and rarely written. State the invalidation strategy.

## 6. Rejecting or parking

Park, with a reason and an unblocker, when a proposal:
- needs a controller, route or DTO change,
- must alter or drop an existing table, column or entity,
- depends on other applications or jobs that write to the same tables and have no agreed owner,
- has no evidence beyond a guess,
- would remove something based on static data alone.

## 7. Sizing benefit and risk

Benefit confidence: `measured` (Query Store or timings support it), `estimated` (reasoned from the audit, such as a NOT-COVERED predicate on a large table), `unmeasured` (no data). Never quote percentages without measurements.

Risk: low (additive index, new read-only path), medium (new tables with dual writes), high (table split with live data movement and many writers). Effort: S / M / L, counting code, migration, tests and validation.
