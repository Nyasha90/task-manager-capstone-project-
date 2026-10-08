# Task Manager (DevOps Capstone)

Flask + SQLAlchemy app. Set `DATABASE_URL` (e.g. `postgresql://user:pass@db:5432/tasks`),
`SECRET_KEY`, `APP_VERSION` via environment.

Run locally:  `pip install -r requirements.txt && python -m flask --app wsgi run`
Test:         `pytest --cov=app`
Endpoints:    `/health`, `/metrics`, `/api/auth/*`, `/api/tasks`, `/api/tasks/<id>`
