# DB_OPTIMIZATION_PLAN.md template

Use this structure and these table headers **exactly**: `scripts/build_plan_outputs.py` recognizes each table by its header text and turns it into an Excel sheet and a CSV. Keep IDs in backticks, one row per fact, and separate lists inside a cell with `;`. Escape a literal pipe as `\|`.

```markdown
# Database Optimization Plan

- Generated: <date>, from audit <file/commit>
- Stack: .NET <ver>, EF Core <ver>, SQL Server (Azure SQL <tier>)
- Status: PLAN ONLY. No code, migration or database change has been made.
- Constraints applied: API contract frozen; existing code and tables immutable; new behind a switch; additive schema only.

## 0. Summary and completeness gate
| Metric | Value |
|---|---|
| Proposals accepted | n |
| Proposals parked | n |
| Work packages | n (waves: n) |
| Benefit measured / estimated / unmeasured | n / n / n |

Gate: [x] every proposal has evidence IDs  [x] migration + rollback + test per proposal
[x] each proposal in exactly one package  [x] no file owned by two packages
[x] all controllers unchanged  [x] parked items have reasons  [x] assumptions listed

## 1. Inputs, assumptions and unmeasured items
- Audit inputs and gaps (unresolved items that limit this plan)
- Runtime data available or missing (Query Store, index usage, sizes)
- Environment facts (tier, outside writers, deployment windows)

## 2. Proposals
| Proposal ID | Type | Target tables | Summary | Evidence | Benefit | Benefit confidence | Risk | Effort | Package | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| `PROP-001` | index | Orders | Index on (CustomerId, Status) with INCLUDE (Total) | W-012; W-031; IX-Orders_CustomerId | Removes key lookups on order list | estimated | low | S | PKG-01 | accepted |

Type is one of: index, query-fix, stored-procedure, table-split, normalization, archive, compression, caching, other.

### PROP-001 <title>
Change: DDL sketch or query/procedure shape
New code: new entities / configurations / service / repository (names and folders); interface kept: `IOrderService`
Existing code referenced read-only: files
Existing code that must change (should be none): files and why
Writers of the old table(s): W-ids and how each is covered
Tests: contract / characterization / migration validation
Notes: risks, alternatives considered, what was rejected and why

## 3. Migration, validation and rollback
| Proposal ID | Backfill | Sync strategy | Validation | Cutover | Rollback | Point of no return |
|---|---|---|---|---|---|---|
| `PROP-001` | n/a (index only) | n/a | Compare plan and timings in Query Store | Deploy migration off-peak, ONLINE = ON | Drop index (Down) | none |

## 4. Work packages
| Package ID | Name | Proposals | Workflows | Controllers (unchanged, read-only) | Existing services/repos (read-only) | New files to create | Existing files to modify | Depends on | Owner | Wave |
|---|---|---|---|---|---|---|---|---|---|---|
| `PKG-00` | Foundation and integration | all | - | - | - | src/Services/Optimization/FeatureFlags.cs; ... | Program.cs; AppDbContext.cs | - | integration owner | 0 |

## 5. Shared files and owners
| File | Why shared | Owner package | Rule |
|---|---|---|---|
| src/Data/Migrations/AppDbContextModelSnapshot.cs | Rewritten by every migration | `PKG-00` | Only PKG-00 generates migrations, in merge order |

## 6. Merge order
1. PKG-00 (wave 0): ...
2. Wave 1 (parallel): PKG-01, PKG-02
3. Wave 2: PKG-03 (depends on PKG-01)

## 7. Task briefs
(One per package, using the template in references/work-packages.md)

## 8. Parked proposals
| Proposal ID | Type | Target tables | Reason parked | What would unblock it |
|---|---|---|---|---|

## 9. Open questions and data to collect
- Azure data to pull (Query Store, index usage stats, table sizes) and which proposals it would confirm or change
- Decisions needed from the user (for example outside writers, maintenance windows)
```

## Notes for the writer

- A package's `Controllers` cell is informational. The export script reports an error if a package lists a controller under "Existing files to modify".
- Put a file in `Existing files to modify` only if the change is unavoidable, and prefer assigning that file to `PKG-00`.
- The `Evidence` cell should hold the audit IDs (`W-`, `T-`, `IX-`) and, if available, a measurement reference such as `QS: query_id 4821, 1.2s avg`.
- Keep `Status` to `accepted` or `parked`; parked proposals also appear in section 8.
