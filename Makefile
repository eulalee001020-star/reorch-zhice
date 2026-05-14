.PHONY: demo-reset demo-seed demo-seed-api demo-validate demo-run

demo-reset:
	python demo/scripts/reset_demo_data.py

demo-seed:
	python demo/scripts/seed_demo_data.py

demo-seed-api:
	python demo/scripts/seed_demo_data.py --api-base-url http://localhost:8000/api/v1

demo-validate: demo-seed

demo-run:
	docker compose up --build
