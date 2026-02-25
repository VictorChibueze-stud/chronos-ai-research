from pathlib import Path

from src.core.experiment_registry import create_experiment


def test_create_experiment_creates_structure(tmp_path: Path):
    base = tmp_path / "experiments"
    paths = create_experiment("exp_test", base_dir=base)

    assert (paths.root / "params.yaml").exists()
    assert (paths.root / "data_manifest.json").exists()
    assert (paths.root / "results.json").exists()
    assert (paths.figures_dir / ".gitkeep").exists()


def test_create_experiment_no_overwrite(tmp_path: Path):
    base = tmp_path / "experiments"
    paths = create_experiment("exp_test", base_dir=base)

    p = paths.root / "params.yaml"
    p.write_text("original: true\n")

    # Attempt to create with different params; should NOT overwrite existing file
    create_experiment("exp_test", base_dir=base, params={"foo": "bar"})

    content = p.read_text(encoding="utf-8")
    assert "original: true" in content
