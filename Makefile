.PHONY: check data features train eval api test all

check:
	python scripts/check_data_access.py --json reports/data_access.json

data:
	python -m src.data.build_panel --config config/data.yaml

features:
	python -m src.features.build_features --config config/features.yaml

train:
	python -m src.models.train --config config/model.yaml

eval:
	python -m src.eval.evaluate --config config/model.yaml

api:
	uvicorn src.api.main:app --reload

test:
	pytest -q

all: data features train eval
