"""
IKENGA Sandbox Push Tool
Copies sandbox/algorithms/ files back to live src/ files.
Run from project root: python sandbox/push_to_live.py
Shows diff summary first and asks for confirmation.
"""
import shutil
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).parent.parent

LIVE_MAP = {
    "trend_id.py":         ROOT / "src/core/trend_id.py",
    "global_structure.py": ROOT / "src/scanner/global_structure.py",
    "structural_walker.py": ROOT / "src/core/structural_walker.py",
    "choch_zone.py":       ROOT / "src/core/choch_zone.py",
    "structure_levels.py": ROOT / "src/core/structure_levels.py",
    "filter_defaults.py":  ROOT / "src/core/filter_defaults.py",
}

SANDBOX_DIR = Path(__file__).parent / "algorithms"


def main():
    print("Running diff first...\n")
    result = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "diff_tool.py")],
        capture_output=True, text=True
    )
    print(result.stdout)

    changed = []
    for filename, live_path in LIVE_MAP.items():
        sandbox_path = SANDBOX_DIR / filename
        if not sandbox_path.exists():
            continue
        if sandbox_path.read_text(encoding="utf-8") != \
           live_path.read_text(encoding="utf-8"):
            changed.append(filename)

    if not changed:
        print("Nothing to push.")
        return

    print(f"\nFiles to push: {', '.join(changed)}")
    confirm = input("\nType YES to push to live: ").strip()
    if confirm != "YES":
        print("Aborted.")
        return

    for filename in changed:
        sandbox_path = SANDBOX_DIR / filename
        live_path = LIVE_MAP[filename]
        shutil.copy2(sandbox_path, live_path)
        print(f"Pushed: {filename} → {live_path}")

    print("\nDone. Restart the server to apply changes.")


if __name__ == "__main__":
    main()
