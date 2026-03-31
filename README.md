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
   - `GATE_WIEGAND_TRANSPORT=dry_run` (use `http` only when real transport endpoint exists)
3. Start backend:
   - `py -3.12 -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000`
4. Health check:
   - `http://127.0.0.1:8000/health`

## Test commands
- Backend tests: `py -3.12 -m pytest -q backend/tests`
- Frontend typecheck: `cd frontend && npm run typecheck`

## Full server runbook
Detailed Russian instruction for launch and verification with Gate Server/Terminal/Commander:
- [SERVER_RUNBOOK_RU.md](/e:/savoya/SavoyaApp/SERVER_RUNBOOK_RU.md)
