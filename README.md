# SavoyaApp

## Current deployment mode
Project is prepared for deployment on the same Windows PC where Gate `config.mdb` is located.
Bridge/VPS mode is removed.

## Quick start (server machine)
1. Install dependencies:
   - `py -3.12 -m pip install -r backend/requirements.txt`
2. Configure environment in `.env`:
   - `DATABASE_URL=sqlite+aiosqlite:///./backend_prod.db`
   - `DEBUG=False`
   - `GATE_REAL_INTEGRATION_ENABLED=True`
   - `GATE_MDB_PATH=C:/Gate/Server/config.mdb` (adjust for your server)
   - `GATE_WIEGAND_TRANSPORT=dry_run` (for no-physics test mode)
   - `GATE_WIEGAND_TRANSPORT=http` + `GATE_WIEGAND_HTTP_URL=...` (if transport accepts HTTP)
   - `GATE_WIEGAND_TRANSPORT=tcp` + `GATE_WIEGAND_TCP_HOST=...` + `GATE_WIEGAND_TCP_PORT=...` (if transport accepts raw TCP/IP)
3. Start backend:
   - `py -3.12 -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000`
4. Health check:
   - `http://127.0.0.1:8000/health`
5. For web frontend CORS (optional override):
   - `CORS_ALLOW_ORIGINS_JSON=["http://localhost:8081","http://127.0.0.1:8081"]`

## Frontend web run
1. Install frontend dependencies:
   - `cd frontend && npm install`
2. Start web client (Expo Web):
   - `npm run web`
3. Open in browser:
   - `http://localhost:8081`

## Run Full Stack In Docker
1. Build and start all services:
   - `docker compose up --build -d`
2. Open frontend:
   - `http://localhost`
3. Backend health:
   - `http://localhost:8000/health`

## Test commands
- Backend tests: `py -3.12 -m pytest -q backend/tests`
- Frontend typecheck: `cd frontend && npm run typecheck`

## Full server runbook
Detailed Russian instruction for launch and verification with Gate Server/Terminal/Commander:
- [SERVER_RUNBOOK_RU.md](/e:/savoya/SavoyaApp/SERVER_RUNBOOK_RU.md)
