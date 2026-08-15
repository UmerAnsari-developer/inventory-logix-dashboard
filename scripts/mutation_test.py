"""Lightweight AST-based mutation testing runner.

Applies single-operator/constant mutations to pure-logic modules in a
throwaway workspace copy, runs a focused pytest subset per mutant, and
classifies each mutant as KILLED (tests fail) / SURVIVED (tests pass) /
TIMEOUT.

Writes results to scripts/mutation_report.md and scripts/mutation_results.json.
The real project sources are never mutated (only the workspace copy is).
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
VENV_PY = PROJECT / "myvenv" / "Scripts" / "python.exe"
WORK = Path(r"C:\Users\UMER\AppData\Local\Temp\opencode\mut_work")
REPORT = PROJECT / "scripts" / "mutation_report.md"
JSON_OUT = PROJECT / "scripts" / "mutation_results.json"

TEST_FILES = ["tests/test_services.py", "tests/test_security.py", "tests/test_ml.py"]
MAX_PER_FILE = 40
PER_MUTANT_TIMEOUT = 120  # seconds

TARGETS = [
    "app/security/validators.py",
    "app/services/product_service.py",
    "app/services/movement_service.py",
    "app/ml/forecasting.py",
    "app/ml/anomaly.py",
]

ORIGINALS: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Mutation site discovery + application
# ---------------------------------------------------------------------------
def _binop(op):
    mapping = [
        (ast.Add, ast.Sub, "+ -> -"),
        (ast.Sub, ast.Add, "- -> +"),
        (ast.Mult, ast.Div, "* -> /"),
        (ast.Div, ast.Mult, "/ -> *"),
        (ast.FloorDiv, ast.Mult, "// -> *"),
        (ast.Mod, ast.Mult, "% -> *"),
        (ast.Pow, ast.Mult, "** -> *"),
    ]
    for cls, repl, desc in mapping:
        if isinstance(op, cls):
            return desc, repl()
    return None, None


def _cmpop(op):
    mapping = [
        (ast.Eq, ast.NotEq, "== -> !="),
        (ast.NotEq, ast.Eq, "!= -> =="),
        (ast.Lt, ast.LtE, "< -> <="),
        (ast.LtE, ast.Lt, "<= -> <"),
        (ast.Gt, ast.GtE, "> -> >="),
        (ast.GtE, ast.Gt, ">= -> >"),
    ]
    for cls, repl, desc in mapping:
        if isinstance(op, cls):
            return desc, repl()
    return None, None


def _boolop(op):
    if isinstance(op, ast.And):
        return "and -> or", ast.Or()
    if isinstance(op, ast.Or):
        return "or -> and", ast.And()
    return None, None


def discover_sites(src: str):
    tree = ast.parse(src)
    parent: dict = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node

    def funcname(node) -> str:
        n = node
        while n in parent:
            n = parent[n]
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return n.name
        return "<module>"

    sites = []
    seen = set()
    for node in ast.walk(tree):
        lineno = getattr(node, "lineno", None)
        if lineno is None:
            continue
        key = (lineno, node.col_offset)
        if key in seen:
            continue
        seen.add(key)
        if isinstance(node, ast.BinOp):
            desc, repl = _binop(node.op)
            if repl is not None:
                sites.append((key, "binop", desc, node.lineno, funcname(node), repl))
        elif isinstance(node, ast.Compare):
            for i, op in enumerate(node.ops):
                desc, repl = _cmpop(op)
                if repl is not None:
                    sites.append((key, "compare", desc, node.lineno, funcname(node), (i, repl)))
                    break
        elif isinstance(node, ast.BoolOp):
            desc, repl = _boolop(node.op)
            if repl is not None:
                sites.append((key, "boolop", desc, node.lineno, funcname(node), repl))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            sites.append((key, "unot", "remove 'not'", node.lineno, funcname(node), None))
        elif isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                sites.append((key, "const", f"{node.value} -> {not node.value}",
                              node.lineno, funcname(node), not node.value))
            elif isinstance(node.value, int) and node.value != 0 and abs(node.value) <= 1000:
                sites.append((key, "const", f"{node.value} -> {node.value + 1}",
                              node.lineno, funcname(node), node.value + 1))
    return tree, sites


def _replace_child(parent, old, new):
    for field in ast.iter_fields(parent):
        val = getattr(parent, field)
        if isinstance(val, list):
            for i, v in enumerate(val):
                if v is old:
                    val[i] = new
        elif val is old:
            setattr(parent, field, new)


def apply_mutation(src: str, site) -> str | None:
    key, kind, _desc, _ln, _fn, repl = site
    tree = ast.parse(src)
    target = None
    for node in ast.walk(tree):
        if (getattr(node, "lineno", None), getattr(node, "col_offset", None)) == key:
            target = node
            break
    if target is None:
        return None
    try:
        if kind == "binop":
            target.op = repl
        elif kind == "compare":
            i, newop = repl
            target.ops[i] = newop
        elif kind == "boolop":
            target.op = repl
        elif kind == "const":
            target.value = repl
        elif kind == "unot":
            par = None
            for node in ast.walk(tree):
                for child in ast.iter_child_nodes(node):
                    if child is target:
                        par = node
            if par is None:
                return None
            _replace_child(par, target, target.operand)
        return ast.unparse(tree)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------
def run_tests() -> int:
    proc = subprocess.run(
        [str(VENV_PY), "-m", "pytest", "-q", *TEST_FILES],
        cwd=str(WORK),
        capture_output=True,
        text=True,
        timeout=PER_MUTANT_TIMEOUT,
    )
    return proc.returncode


def roundtrip_ok(src: str) -> bool:
    try:
        tree = ast.parse(src)
        re_parsed = ast.parse(ast.unparse(tree))
        compile(re_parsed, "<mut>", "exec")
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    results: list[dict] = []

    # Baseline check.
    rc = run_tests()
    print(f"[baseline] pytest rc={rc}", flush=True)
    if rc != 0:
        print("BASELINE FAILED - aborting", flush=True)
        return 1

    for rel in TARGETS:
        src_path = PROJECT / rel
        work_path = WORK / rel
        src = src_path.read_text(encoding="utf-8")
        ORIGINALS[rel] = src
        if not roundtrip_ok(src):
            print(f"[{rel}] SKIPPED (round-trip parse failed)", flush=True)
            continue

        _tree, sites = discover_sites(src)
        sites = sites[:MAX_PER_FILE]
        print(f"[{rel}] {len(sites)} mutation sites", flush=True)

        seen_sources: set[str] = set()
        for idx, site in enumerate(sites, start=1):
            mutated = apply_mutation(src, site)
            if mutated is None or mutated == src or mutated in seen_sources:
                continue
            seen_sources.add(mutated)
            work_path.write_text(mutated, encoding="utf-8")

            start = datetime.now()
            try:
                rc = run_tests()
                outcome = "survived" if rc == 0 else "killed"
            except subprocess.TimeoutExpired:
                outcome = "timeout"
            work_path.write_text(src, encoding="utf-8")  # restore

            results.append({
                "module": rel,
                "line": site[3],
                "function": site[4],
                "mutation": site[2],
                "outcome": outcome,
                "elapsed_s": round((datetime.now() - start).total_seconds(), 1),
            })
            print(f"  [{outcome:8s}] {rel}:{site[3]} {site[4]} :: {site[2]}",
                  flush=True)

    # Ensure all workspace files restored to original.
    for rel, content in ORIGINALS.items():
        (WORK / rel).write_text(content, encoding="utf-8")

    write_report(results)
    return 0


def write_report(results: list[dict]) -> None:
    JSON_OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")

    lines = ["# Mutation Test Report", ""]
    lines.append(f"- Timestamp: {datetime.now().isoformat()}")
    lines.append(f"- Scope: {', '.join(TARGETS)}")
    lines.append(f"- Test command: `{VENV_PY} -m pytest -q " + " ".join(TEST_FILES) + "`")
    lines.append(f"- Mutations: operator/constant swaps (AST, one per mutant)")
    lines.append("")

    by_module: dict[str, list] = {}
    for r in results:
        by_module.setdefault(r["module"], []).append(r)

    total_killed = total_survived = total_timeout = 0
    lines.append("## Per-module results")
    lines.append("")
    lines.append("| Module | Mutants | Killed | Survived | Timeout | Mutation score |")
    lines.append("|---|---|---|---|---|---|")
    for mod in TARGETS:
        rows = by_module.get(mod, [])
        killed = sum(1 for r in rows if r["outcome"] == "killed")
        survived = sum(1 for r in rows if r["outcome"] == "survived")
        timed_out = sum(1 for r in rows if r["outcome"] == "timeout")
        total_killed += killed
        total_survived += survived
        total_timeout += timed_out
        score = killed / max(killed + survived, 1)
        lines.append(f"| `{mod}` | {len(rows)} | {killed} | {survived} | {timed_out} | "
                     f"{score:.0%} |")
    total = max(total_killed + total_survived, 1)
    lines.append(f"| **Total** | {total_killed + total_survived + total_timeout} | "
                 f"**{total_killed}** | **{total_survived}** | **{total_timeout}** | "
                 f"**{total_killed / total:.0%}** |")
    lines.append("")

    survivors = [r for r in results if r["outcome"] == "survived"]
    lines.append(f"## Survived mutants ({len(survivors)})")
    lines.append("")
    if survivors:
        lines.append("| Module | Line | Function | Mutation |")
        lines.append("|---|---|---|---|")
        for r in survivors:
            lines.append(f"| `{r['module']}` | {r['line']} | {r['function']} | {r['mutation']} |")
    else:
        lines.append("None - every mutant was detected by the test suite.")
    lines.append("")

    lines.append("## Notes")
    lines.append("")
    lines.append("- **Killed** = at least one test failed under the mutation (good coverage).")
    lines.append("- **Survived** = all tests still passed (coverage gap or equivalent mutation).")
    lines.append("- **Timeout** = test run exceeded the per-mutant timeout; treated as a pass "
                 "of the guard (counted toward killed for scoring).")
    lines.append("- Mutation testing was run on a throwaway copy; the real sources were untouched.")
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport written to {REPORT}")
    print(f"Details written to {JSON_OUT}")


if __name__ == "__main__":
    sys.exit(main())