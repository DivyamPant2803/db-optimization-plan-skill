#!/usr/bin/env python3
"""Profile a DB usage audit (CSV) for the db-optimization-plan skill.

Reads one or more audit CSVs (flat or wide, e.g. the Access_Flat or
Workflow_Access sheets exported by db-usage-audit), normalizes them, and writes
a JSON profile with, per table: readers/writers, per-column usage by role,
column groups used by identical workflow sets (split candidates), unindexed
predicates, hub tables, and connected groups of tables (work-package seeds).

Usage:
  analyze_audit.py <file-or-folder> [more ...] [--out profile.json]
                   [--map workflow=Header --map table=Header ...]

--map overrides header detection. Keys: workflow, table, column, role, op,
coverage, index. Python 3.8+, standard library only.
"""
import argparse
import csv
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict

ALIASES = {
    "workflow": ["workflow", "workflow id", "workflowid", "w id", "wid", "endpoint", "entry point", "api", "trigger"],
    "table": ["table", "table name", "tablename"],
    "column": ["column", "column name", "columnname"],
    "role": ["role", "access", "access type", "usage", "usage type", "column role"],
    "op": ["op", "operation", "operation type", "action"],
    "coverage": ["index coverage", "coverage", "index status", "indexed", "has index", "is indexed"],
    "index": ["index", "index id", "index name", "matched index"],
}
WIDE_ROLES = [
    ("columns read", "READ"), ("filter columns", "FILTER"), ("join columns", "JOIN"),
    ("sort/group", "SORT_GROUP"), ("sort / group", "SORT_GROUP"), ("sort group", "SORT_GROUP"),
    ("columns written", "WRITE"),
]
PREDICATE_ROLES = {"FILTER", "JOIN", "SORT_GROUP"}
WRITE_ROLES = {"WRITE", "DELETE"}
GOOD_COVERAGE = {"COVERED-SEEK", "COVERED-INCLUDE"}
EMPTY = {"", "-", "n/a", "none", "null"}


def norm_header(h):
    return re.sub(r"[\s_\-]+", " ", (h or "").strip().lower())


def norm_role(text):
    t = (text or "").strip().lower()
    if not t:
        return None
    if any(k in t for k in ("filter", "where", "predicate")):
        return "FILTER"
    if "join" in t:
        return "JOIN"
    if any(k in t for k in ("sort", "order", "group")):
        return "SORT_GROUP"
    if "delete" in t:
        return "DELETE"
    if any(k in t for k in ("insert", "update", "write", "set", "upsert", "merge", "bulk")):
        return "WRITE"
    if any(k in t for k in ("read", "select", "project")):
        return "READ"
    return None


def norm_coverage(text):
    t = (text or "").strip().upper()
    if not t:
        return ""
    for label in ("COVERED-SEEK", "COVERED-PARTIAL", "COVERED-INCLUDE", "NOT-COVERED", "UNKNOWN"):
        if label in t:
            return label
    if t in ("YES", "Y", "TRUE", "1"):
        return "COVERED-SEEK"
    if t in ("NO", "N", "FALSE", "0"):
        return "NOT-COVERED"
    return t


def parse_cov_cell(cell):
    """'CustomerId: COVERED-SEEK (IX-A); Status: NOT-COVERED' -> {col: (label, index)}"""
    out = {}
    for part in re.split(r"[;\n]", cell or ""):
        m = re.match(r"\s*([^:]+):\s*([A-Z\-]+)\s*(?:\(([^)]*)\))?", part)
        if m:
            out[m.group(1).strip()] = (m.group(2), (m.group(3) or "").strip())
    return out


def split_cols(cell):
    if (cell or "").strip().lower() in EMPTY:
        return []
    out = []
    for p in re.split(r"[,;\n]", cell):
        name = re.sub(r"\s*\(.*?\)\s*$", "", p.strip())
        if name and name.lower() not in EMPTY:
            out.append(name)
    return out


def detect(headers, overrides):
    normed = {norm_header(h): h for h in headers}
    found = {}
    for key, names in ALIASES.items():
        if key in overrides:
            found[key] = overrides[key]
            continue
        for n in names:
            if n in normed:
                found[key] = normed[n]
                break
    wide = {}
    for label, role in WIDE_ROLES:
        if label in normed:
            wide[normed[label]] = role
    return found, wide


def load_csv(path, overrides):
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        found, wide = detect(headers, overrides)
        flat_ok = all(k in found for k in ("workflow", "table", "column"))
        wide_ok = all(k in found for k in ("workflow", "table")) and bool(wide)
        if not (flat_ok or wide_ok):
            return None, headers
        rows = []
        for r in reader:
            wf = (r.get(found["workflow"]) or "").strip()
            tb = (r.get(found["table"]) or "").strip()
            if not wf or not tb:
                continue
            op = norm_role(r.get(found.get("op", ""), "")) if "op" in found else None
            cov_cell = r.get(found.get("coverage", ""), "") if "coverage" in found else ""
            idx = (r.get(found.get("index", ""), "") or "").strip() if "index" in found else ""
            if flat_ok:
                col = (r.get(found["column"]) or "").strip()
                if not col or col.lower() in EMPTY:
                    continue
                role = norm_role(r.get(found.get("role", ""), "")) if "role" in found else None
                role = role or op or "UNKNOWN"
                label = norm_coverage(cov_cell)
                rows.append((wf, tb, col, role, label, idx))
            else:
                cov = parse_cov_cell(cov_cell)
                for header, role in wide.items():
                    for col in split_cols(r.get(header, "")):
                        label, ix = cov.get(col, (norm_coverage(""), ""))
                        rows.append((wf, tb, col, role, label, ix or idx))
                if op in WRITE_ROLES:
                    # keep writer info even if no column list was given
                    rows.append((wf, tb, "*", op, "", ""))
        return rows, headers


class DSU:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def build_profile(rows):
    tables = {}
    wf_tables = defaultdict(set)
    for wf, tb, col, role, label, ix in rows:
        t = tables.setdefault(tb, {"workflows": set(), "readers": set(), "writers": set(), "columns": {}})
        t["workflows"].add(wf)
        wf_tables[wf].add(tb)
        if role in WRITE_ROLES:
            t["writers"].add(wf)
        else:
            t["readers"].add(wf)
        c = t["columns"].setdefault(col, {"roles": Counter(), "workflows": set(), "coverage": Counter(),
                                          "indexes": set(), "pred": defaultdict(set)})
        c["roles"][role] += 1
        c["workflows"].add(wf)
        if label:
            c["coverage"][label] += 1
        if ix:
            c["indexes"].add(ix)
        if role in PREDICATE_ROLES:
            c["pred"][label or "UNKNOWN"].add(wf)

    total_wf = len(wf_tables)
    hub_cut = max(5, int(0.2 * total_wf + 0.5))

    dsu = DSU()
    for wf, tbs in wf_tables.items():
        tbs = sorted(tbs)
        for t in tbs:
            dsu.find(t)
        for t in tbs[1:]:
            dsu.union(tbs[0], t)
    comps = defaultdict(list)
    for t in tables:
        comps[dsu.find(t)].append(t)

    out_tables = {}
    unindexed = []
    for tb, t in sorted(tables.items()):
        groups = defaultdict(list)
        for col, c in t["columns"].items():
            if col == "*":
                continue
            groups[frozenset(c["workflows"])].append(col)
        group_list = sorted(({"columns": sorted(cols), "workflows": sorted(wfs)} for wfs, cols in groups.items()),
                            key=lambda g: (-len(g["columns"]), g["workflows"]))
        disjoint = 0
        for i in range(len(group_list)):
            for j in range(i + 1, len(group_list)):
                if not set(group_list[i]["workflows"]) & set(group_list[j]["workflows"]):
                    disjoint += 1
        cols_out = {}
        for col, c in sorted(t["columns"].items()):
            cols_out[col] = {
                "roles": dict(c["roles"]),
                "workflow_count": len(c["workflows"]),
                "workflows": sorted(c["workflows"]),
                "coverage": dict(c["coverage"]),
                "indexes": sorted(c["indexes"]),
            }
            for label, wfs in c["pred"].items():
                if label not in GOOD_COVERAGE:
                    unindexed.append({"table": tb, "column": col, "coverage": label,
                                      "workflows": sorted(wfs), "workflow_count": len(wfs)})
        out_tables[tb] = {
            "workflow_count": len(t["workflows"]),
            "reader_count": len(t["readers"]),
            "writer_count": len(t["writers"]),
            "writers": sorted(t["writers"]),
            "is_hub": len(t["workflows"]) >= hub_cut,
            "column_groups": group_list,
            "split_candidate": len(group_list) >= 2 and disjoint >= 1,
            "disjoint_group_pairs": disjoint,
            "columns": cols_out,
        }
    unindexed.sort(key=lambda u: (-u["workflow_count"], u["table"], u["column"]))
    comps_out = sorted(({"tables": sorted(v), "workflow_count": len({w for w, tbs in wf_tables.items() if tbs & set(v)})}
                        for v in comps.values()), key=lambda c: (-len(c["tables"]), c["tables"]))
    return {
        "summary": {"tables": len(tables), "workflows": total_wf, "access_rows": len(rows), "hub_threshold": hub_cut},
        "tables": out_tables,
        "unindexed_predicates": unindexed,
        "connected_table_groups": comps_out,
    }


def collect_files(paths):
    files = []
    for p in paths:
        if os.path.isdir(p):
            files += sorted(glob.glob(os.path.join(p, "**", "*.csv"), recursive=True))
        elif os.path.isfile(p):
            files.append(p)
        else:
            print(f"warn: {p} not found", file=sys.stderr)
    return files


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--out", default=".db-plan-work/profile.json")
    ap.add_argument("--map", action="append", default=[], metavar="KEY=HEADER")
    args = ap.parse_args()

    overrides = {}
    for m in args.map:
        if "=" not in m:
            sys.exit(f"error: --map expects KEY=HEADER, got {m}")
        k, v = m.split("=", 1)
        if k not in ALIASES:
            sys.exit(f"error: unknown key {k}; valid: {', '.join(ALIASES)}")
        overrides[k] = v

    all_rows = []
    used, skipped = [], []
    for f in collect_files(args.inputs):
        rows, headers = load_csv(f, overrides)
        if rows is None:
            skipped.append((f, headers))
        else:
            used.append((f, len(rows)))
            all_rows += rows
    if not all_rows:
        print("error: could not map any CSV to workflow/table/column data.", file=sys.stderr)
        for f, h in skipped:
            print(f"  {f}: headers = {h}", file=sys.stderr)
        print("Use --map workflow=<header> --map table=<header> --map column=<header> [--map role=<header>].",
              file=sys.stderr)
        sys.exit(2)

    profile = build_profile(all_rows)
    out = args.out
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(profile, fh, indent=2)

    s = profile["summary"]
    print(f"Profile written to {out}")
    for f, n in used:
        print(f"  used {f} ({n} rows)")
    for f, h in skipped:
        print(f"  skipped {f} (headers not recognised: {h[:6]})")
    print(f"\n{s['tables']} tables, {s['workflows']} workflows, {s['access_rows']} access rows (hub threshold {s['hub_threshold']} workflows)")
    print("\nTop tables by workflows (readers/writers):")
    ranked = sorted(profile["tables"].items(), key=lambda kv: -kv[1]["workflow_count"])[:10]
    for tb, t in ranked:
        flags = []
        if t["is_hub"]:
            flags.append("HUB")
        if t["split_candidate"]:
            flags.append("split-candidate")
        print(f"  {tb:30s} {t['workflow_count']:4d} wf  R{t['reader_count']}/W{t['writer_count']}  {' '.join(flags)}")
    print("\nConnected table groups (work-package seeds):")
    for c in profile["connected_table_groups"][:10]:
        print(f"  {len(c['tables'])} tables, {c['workflow_count']} workflows: {', '.join(c['tables'][:8])}{' ...' if len(c['tables']) > 8 else ''}")
    print("\nTop unindexed/partial predicates:")
    for u in profile["unindexed_predicates"][:10]:
        print(f"  {u['table']}.{u['column']}  {u['coverage']}  ({u['workflow_count']} wf)")
    print("\nThis is a starting point: verify top candidates against the real code before proposing.")


if __name__ == "__main__":
    main()
