.PHONY: demo-reset demo-seed demo-seed-api demo-validate demo-run demo-lite demo-lite-serve lint test

demo-reset:
	python demo/scripts/reset_demo_data.py

demo-seed:
	python demo/scripts/seed_demo_data.py

demo-seed-api:
	python demo/scripts/seed_demo_data.py --api-base-url http://localhost:8000/api/v1

demo-validate: demo-seed

demo-run:
	docker compose up --build

# 不依赖 Postgres / Redis / Kafka 的本地演示
demo-lite:
	python tools/run_local_demo.py

demo-lite-serve:
	python tools/run_local_demo.py --serve

lint:
	ruff check .
	ruff format --check .

test:
	pytest -q
