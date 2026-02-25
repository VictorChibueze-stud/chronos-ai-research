from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

import json
import uuid
import yaml


EXPERIMENTS_ROOT = Path("experiments")


@dataclass
class ExperimentPaths:
    root: Path
    params_path: Path
    data_manifest_path: Path
    results_path: Path
    figures_dir: Path


def _default_experiment_id() -> str:
    """Return a deterministic-ish id: 'exp_YYYYMMDD_HHMMSS_<uuid4short>'."""
    now = datetime.now(timezone.utc)
    short = uuid.uuid4().hex[:8]
    return f"exp_{now.strftime('%Y%m%d_%H%M%S')}_{short}"


def create_experiment(
    exp_id: Optional[str] = None,
    base_dir: Path = EXPERIMENTS_ROOT,
    *,
    params: Optional[Dict[str, Any]] = None,
    data_manifest: Optional[Dict[str, Any]] = None,
    results: Optional[Dict[str, Any]] = None,
) -> ExperimentPaths:
    """
    Create (or re-use) an experiment directory with standard files:

    experiments/<exp_id>/
      - params.yaml
      - data_manifest.json
      - results.json
      - figures/ (directory with .gitkeep)

    Behavior:
    - If exp_id is None, generate one via _default_experiment_id().
    - If files already exist, do NOT overwrite; only create missing ones.
    - If params/data_manifest/results are provided and files do not exist yet,
      write those initial contents.
    - Always return ExperimentPaths with existing/new paths.
    """
    base_dir.mkdir(parents=True, exist_ok=True)
    if exp_id is None:
        exp_id = _default_experiment_id()

    root = base_dir / exp_id
    root.mkdir(parents=True, exist_ok=True)

    params_path = root / "params.yaml"
    data_manifest_path = root / "data_manifest.json"
    results_path = root / "results.json"
    figures_dir = root / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    # create .gitkeep in figures
    gitkeep = figures_dir / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.write_text("", encoding="utf-8")

    # Write params.yaml if provided and missing
    if params is not None and not params_path.exists():
        with params_path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(params, fh)
    else:
        # ensure file exists
        if not params_path.exists():
            params_path.write_text("# params\n", encoding="utf-8")

    # Write data_manifest.json if provided and missing
    if data_manifest is not None and not data_manifest_path.exists():
        with data_manifest_path.open("w", encoding="utf-8") as fh:
            json.dump(data_manifest, fh, indent=2, ensure_ascii=False)
    else:
        if not data_manifest_path.exists():
            data_manifest_path.write_text("{}", encoding="utf-8")

    # Write results.json if provided and missing
    if results is not None and not results_path.exists():
        with results_path.open("w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=2, ensure_ascii=False)
    else:
        if not results_path.exists():
            results_path.write_text("{}", encoding="utf-8")

    return ExperimentPaths(
        root=root,
        params_path=params_path,
        data_manifest_path=data_manifest_path,
        results_path=results_path,
        figures_dir=figures_dir,
    )
