#!/usr/bin/env python3
"""Turn DB_OPTIMIZATION_PLAN.md into CSV and Excel files, and check the plan.

Reads the plan's markdown pipe tables (see references/plan-template.md),
recognises each by its header text, and writes:

  <out>.xlsx                  (only if openpyxl is installed)
  <out>_csv/<Sheet>.csv       (always; stdlib only)

Sheets: Proposals, Migration_Plan, Work_Packages, Shared_Files, File_Overlap,
Package_Overlap, Parked, Issues.

It also checks the plan and exits with status 1 if it finds errors:
  - a file owned by more than one package, or a shared file edited by a
    package other than its owner
  - a controller listed under "Existing files to modify"
  - an accepted proposal in no package, or in more than one
  - an accepted proposal with no evidence or with no migration row

Usage: build_plan_outputs.py <plan.md> [--out DB_OPTIMIZATION_PLAN]
Python 3.8+.
"""
import argparse
import csv
import os
import re
import sys
from collections import defaultdict

CELL_LIMIT = 32000
SKIP_TOKENS = {"", "-", "n/a", "none", "...", "all", "tbd"}


def clean(text):
    t = text.strip().replace("\\|", "|").replace("`", "")
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    return t[:CELL_LIMIT]


def split_row(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [clean(c) for c in re.split(r"(?<!\\)\|", s)]


def is_sep(line):
    return bool(re.match(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$", line))


def parse_tables(text):
    lines = text.splitlines()
    in_code = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            in_code = not in_code
            i += 1
            continue
        if not in_code and line.lstrip().startswith("|") and i + 1 < len(lines) and is_sep(lines[i + 1]):
            headers = split_row(line)
            rows = []
            j = i + 2
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                r = split_row(lines[j])
                r += [""] * (len(headers) - len(r))
                rows.append(r[: len(headers)])
                j += 1
            yield headers, rows
            i = j
            continue
        i += 1


def classify(headers):
    h = [x.lower() for x in headers]
    has = lambda n: any(x.startswith(n) for x in h)
    if has("reason parked"):
        return "Parked"
    if has("backfill"):
        return "Migration_Plan"
    if has("proposal id") and has("summary"):
        return "Proposals"
    if has("package id") and has("new files to create"):
        return "Work_Packages"
    if has("file") and has("owner package"):
        return "Shared_Files"
    return None


def col(headers, name):
    for n, h in enumerate(headers):
        if h.lower().startswith(name.lower()):
            return n
    return -1


def get(row, headers, name):
    n = col(headers, name)
    return row[n] if n >= 0 else ""


def items(cell):
    out = []
    for p in re.split(r"[;\n]", cell or ""):
        p = p.strip()
        if p.lower() not in SKIP_TOKENS:
            out.append(p)
    return out


def norm_path(p):
    return p.replace("\\", "/").strip().lower()


def ids(cell):
    return [x.strip() for x in re.split(r"[;,\n]", cell or "") if x.strip() and x.strip().lower() not in SKIP_TOKENS]


def analyze(sheets):
    issues = []   # (severity, area, message)
    prop_h, prop_rows = sheets.get("Proposals", ([], []))
    pkg_h, pkg_rows = sheets.get("Work_Packages", ([], []))
    mig_h, mig_rows = sheets.get("Migration_Plan", ([], []))
    sh_h, sh_rows = sheets.get("Shared_Files", ([], []))

    pkg_ids = {get(r, pkg_h, "package id") for r in pkg_rows}
    shared_owner = {norm_path(get(r, sh_h, "file")): get(r, sh_h, "owner package") for r in sh_rows}

    # file -> list of (package, kind)
    file_use = defaultdict(list)
    pkg_files = {}
    pkg_tables = defaultdict(set)
    for r in pkg_rows:
        pid = get(r, pkg_h, "package id")
        new_f = items(get(r, pkg_h, "new files to create"))
        mod_f = items(get(r, pkg_h, "existing files to modify"))
        pkg_files[pid] = (new_f, mod_f)
        for f in new_f:
            file_use[norm_path(f)].append((pid, "new", f))
        for f in mod_f:
            file_use[norm_path(f)].append((pid, "modify", f))
            if re.search(r"controller", f, re.I):
                issues.append(("error", "controllers", f"{pid} lists a controller under 'Existing files to modify': {f}"))

    for fkey, uses in file_use.items():
        pkgs = sorted({u[0] for u in uses})
        owner = shared_owner.get(fkey)
        if len(pkgs) > 1:
            if owner and set(pkgs) <= {owner}:
                continue
            issues.append(("error", "overlap", f"File {uses[0][2]} is listed by multiple packages: {', '.join(pkgs)}"))
        if owner:
            for p, kind, f in uses:
                if p != owner:
                    issues.append(("error", "shared-file", f"{p} lists shared file {f}, owned by {owner}"))

    # proposals vs packages
    in_pkg = defaultdict(set)
    for r in pkg_rows:
        pid = get(r, pkg_h, "package id")
        for prop in ids(get(r, pkg_h, "proposals")):
            in_pkg[prop].add(pid)
    mig_ids = {get(r, mig_h, "proposal id") for r in mig_rows}
    for r in prop_rows:
        prop = get(r, prop_h, "proposal id")
        status = get(r, prop_h, "status").lower()
        if status == "parked":
            continue
        if not get(r, prop_h, "evidence").strip():
            issues.append(("error", "evidence", f"{prop} has no evidence"))
        pk = get(r, prop_h, "package").strip()
        pkgs = in_pkg.get(prop, set())
        if not pkgs and not pk:
            issues.append(("error", "package", f"{prop} is not assigned to any package"))
        if len(pkgs) > 1:
            issues.append(("error", "package", f"{prop} appears in several packages: {', '.join(sorted(pkgs))}"))
        if pk and pk not in pkg_ids and pk.lower() not in SKIP_TOKENS:
            issues.append(("error", "package", f"{prop} references unknown package {pk}"))
        if pk and pkgs and pk not in pkgs:
            issues.append(("warn", "package", f"{prop}: Package column says {pk} but package table lists {', '.join(sorted(pkgs))}"))
        if prop not in mig_ids:
            issues.append(("error", "migration", f"{prop} has no row in the migration/rollback table"))
        for pid_ in (pk,):
            if pid_ in pkg_ids:
                for t in ids(get(r, prop_h, "target tables")):
                    pkg_tables[pid_].add(t.lower())

    # package-pair overlap (files and tables)
    pair_rows = []
    pkgs_sorted = sorted(pkg_files)
    for i in range(len(pkgs_sorted)):
        for j in range(i + 1, len(pkgs_sorted)):
            a, b = pkgs_sorted[i], pkgs_sorted[j]
            fa = {norm_path(x) for x in pkg_files[a][0] + pkg_files[a][1]}
            fb = {norm_path(x) for x in pkg_files[b][0] + pkg_files[b][1]}
            shared_f = sorted(fa & fb)
            shared_t = sorted(pkg_tables[a] & pkg_tables[b])
            if shared_f or shared_t:
                pair_rows.append([a, b, "; ".join(shared_f), "; ".join(shared_t)])

    overlap_rows = []
    for fkey, uses in sorted(file_use.items()):
        pkgs = sorted({u[0] for u in uses})
        owner = shared_owner.get(fkey, "")
        conflict = "yes" if (len(pkgs) > 1 and not (owner and set(pkgs) <= {owner})) or (owner and any(u[0] != owner for u in uses)) else ""
        for p, kind, f in uses:
            overlap_rows.append([f, p, kind, owner, "; ".join(x for x in pkgs if x != p), conflict])
    return issues, overlap_rows, pair_rows


def write_csv(path, headers, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows)


def write_xlsx(path, sheets):
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError:
        return False
    wb = Workbook()
    wb.remove(wb.active)
    for name, (headers, rows) in sheets.items():
        ws = wb.create_sheet(title=name[:31])
        ws.append(headers)
        for r in rows:
            ws.append(r)
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="1F3864")
            c.alignment = Alignment(vertical="center", wrap_text=True)
        ws.freeze_panes = "A2"
        if rows:
            ws.auto_filter.ref = ws.dimensions
        for n, h in enumerate(headers, 1):
            longest = max([len(str(h))] + [len(str(r[n - 1])) for r in rows[:500] if n - 1 < len(r)])
            ws.column_dimensions[get_column_letter(n)].width = min(max(10, longest + 2), 60)
        for row in ws.iter_rows(min_row=2):
            for c in row:
                c.alignment = Alignment(vertical="top", wrap_text=True)
    wb.save(path)
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan")
    ap.add_argument("--out", default="DB_OPTIMIZATION_PLAN")
    args = ap.parse_args()

    with open(args.plan, encoding="utf-8") as f:
        text = f.read()

    sheets = {}
    for headers, rows in parse_tables(text):
        kind = classify(headers)
        if kind is None:
            continue
        if kind in sheets:
            sheets[kind] = (sheets[kind][0], sheets[kind][1] + rows)
        else:
            sheets[kind] = (headers, rows)

    needed = ["Proposals", "Work_Packages", "Migration_Plan"]
    missing = [n for n in needed if n not in sheets]
    if not sheets:
        sys.exit("error: no recognisable tables. Does the plan follow references/plan-template.md?")

    issues, overlap_rows, pair_rows = analyze(sheets)
    for n in missing:
        issues.append(("error", "structure", f"No '{n}' table found in the plan (check the headers match the template)"))

    out_sheets = dict(sheets)
    out_sheets["File_Overlap"] = (["File", "Package", "Kind", "Shared-file owner", "Also listed by", "Conflict"], overlap_rows)
    out_sheets["Package_Overlap"] = (["Package A", "Package B", "Shared files", "Shared tables"], pair_rows)
    out_sheets["Issues"] = (["Severity", "Area", "Message"], [list(i) for i in issues])

    order = ["Proposals", "Migration_Plan", "Work_Packages", "Shared_Files", "File_Overlap",
             "Package_Overlap", "Parked", "Issues"]
    ordered = {k: out_sheets[k] for k in order if k in out_sheets}

    base = args.out[:-5] if args.out.lower().endswith(".xlsx") else args.out
    csv_dir = base + "_csv"
    os.makedirs(csv_dir, exist_ok=True)
    for name, (h, r) in ordered.items():
        write_csv(os.path.join(csv_dir, name + ".csv"), h, r)
    xlsx_ok = write_xlsx(base + ".xlsx", ordered)

    print(f"Wrote CSVs to {os.path.abspath(csv_dir)}")
    if xlsx_ok:
        print(f"Wrote {os.path.abspath(base + '.xlsx')}")
    else:
        print("openpyxl not installed: skipped .xlsx (pip install --user openpyxl). The CSVs open directly in Excel.")
    for name, (h, r) in ordered.items():
        print(f"  {name:16s} {len(r)} rows")

    errors = [i for i in issues if i[0] == "error"]
    warns = [i for i in issues if i[0] == "warn"]
    print(f"\nChecks: {len(errors)} error(s), {len(warns)} warning(s)")
    for sev, area, msg in issues:
        print(f"  [{sev.upper()}] {area}: {msg}")
    if errors:
        print("\nFix the plan and re-run until there are no errors.")
        sys.exit(1)


if __name__ == "__main__":
    main()
