from __future__ import annotations

import subprocess
import sys
from pathlib import Path


DASHBOARD_PATH = Path(__file__).resolve().parents[1] / "src" / "ui" / "dashboard.py"


def main() -> int:
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(DASHBOARD_PATH)],
        check=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())