"""
IKENGA Sandbox Diff Tool
Compares sandbox/algorithms/ against live src/ files.
Run from project root: python sandbox/diff_tool.py
"""
import ast
import difflib
from pathlib import Path

ROOT = Path(__file__).parent.parent

LIVE_MAP = {
    "trend_id.py":        ROOT / "src/core/trend_id.py",
    "global_structure.py": ROOT / "src/scanner/global_structure.py",
    "structural_walker.py": ROOT / "src/core/structural_walker.py",
    "choch_zone.py":      ROOT / "src/core/choch_zone.py",
    "structure_levels.py": ROOT / "src/core/structure_levels.py",
    "filter_defaults.py": ROOT / "src/core/filter_defaults.py",
}

SANDBOX_DIR = Path(__file__).parent / "algorithms"


def extract_functions(source: str) -> dict[str, str]:
    """Extract top-level function and class bodies keyed by name."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    funcs = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if isinstance(node, ast.ClassDef):
                name = f"class:{node.name}"
            else:
                name = node.name
            lines = source.splitlines()
            start = node.lineno - 1
            end = node.end_lineno
            funcs[name] = "\n".join(lines[start:end])
    return funcs


def diff_file(filename: str) -> list[str]:
    sandbox_path = SANDBOX_DIR / filename
    live_path = LIVE_MAP.get(filename)

    if not sandbox_path.exists():
        return [f"  MISSING in sandbox"]
    if not live_path or not live_path.exists():
        return [f"  MISSING in live"]

    sandbox_src = sandbox_path.read_text(encoding="utf-8")
    live_src = live_path.read_text(encoding="utf-8")

    sandbox_funcs = extract_functions(sandbox_src)
    live_funcs = extract_functions(live_src)

    results = []
    all_names = sorted(set(sandbox_funcs) | set(live_funcs))

    for name in all_names:
        in_sandbox = name in sandbox_funcs
        in_live = name in live_funcs

        if in_sandbox and not in_live:
            results.append(f"  + {name}  [NEW in sandbox]")
        elif in_live and not in_sandbox:
            results.append(f"  - {name}  [REMOVED from sandbox]")
        elif sandbox_funcs[name] != live_funcs[name]:
            results.append(f"  ~ {name}  [MODIFIED]")

    return results if results else ["  (no changes)"]


def main():
    print("=" * 60)
    print("IKENGA SANDBOX vs LIVE DIFF")
    print("=" * 60)
    any_change = False
    for filename in LIVE_MAP:
        changes = diff_file(filename)
        has_change = any(
            "[NEW" in c or "[MODIFIED" in c or "[REMOVED" in c
            for c in changes
        )
        if has_change:
            any_change = True
        status = "CHANGED" if has_change else "unchanged"
        print(f"\n{filename}  [{status}]")
        for line in changes:
            print(line)

    print("\n" + "=" * 60)
    if any_change:
        print("Changes detected. Review above before pushing to live.")
    else:
        print("Sandbox matches live. No changes to push.")
    print("=" * 60)


if __name__ == "__main__":
    main()
