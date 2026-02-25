# Experiments

Each experiment run is stored under `experiments/<exp_id>/` with:

- `params.yaml` – parameters used for the run.
- `data_manifest.json` – which data files and slices were used.
- `results.json` – metrics and summary results.
- `figures/` – plots exported from notebooks.

Use `src.core.experiment_registry.create_experiment()` to create and manage runs.
