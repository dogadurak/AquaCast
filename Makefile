.PHONY: check grid export-chirps export-era5 export-all panel spi data \
        baselines train eval test all

# Fixed at the start of Phase 1 - this file referenced modules that never
# existed (src.features.build_features, src.eval.evaluate) and passed a
# --config flag no script here parses (every module reads its config path
# internally via src.data.gee_io.load_config(), per CLAUDE.md's "no magic
# numbers, config in config/*.yaml" rule - a CLI flag pointing at the same
# path would be redundant, not wrong, but none of these scripts accept one,
# so the flag was silently ignored rather than doing anything). None of this
# was caught earlier because nothing in Phase 0 ran `make` - every step was
# invoked directly as `python -m ...` during development.

check:
	python scripts/check_data_access.py --json reports/data_access.json

# --- GEE-touching steps: slow, consume Earth Engine quota, need `earthengine
# authenticate` first. Kept separate from the fast local steps below so
# `make data` cannot surprise anyone with a multi-hour job. ---
grid:
	python -m src.data.grid

export-chirps:
	python -m src.data.export_chirps

export-era5:
	python -m src.data.export_era5

export-all: grid export-chirps export-era5

# --- Local-only steps: read the exported CSVs already on disk, no GEE calls,
# fast, safe to rerun while iterating. ---
panel:
	python -m src.data.build_panel

spi:
	python -m src.features.spi

data: panel spi

baselines:
	python -m src.models.baselines

train:
	python -m src.models.train

eval:
	python -m src.eval.skill

test:
	pytest -q

# The Phase 0 pipeline end to end, GEE exports excluded (see export-all) -
# assumes data/interim/*.csv already exist from a prior export-all run.
all: data baselines train eval
