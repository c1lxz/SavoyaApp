# SavoyaApp

## Test Prep

### Runtime versions
- Python: 3.12
- Node.js: use project lockfile (`frontend/package-lock.json`) and Expo from `frontend/package.json` (`expo ~51.0.28`)

### Environment checklist
Use `test.env` and verify these variables are set before tests:
- `DATABASE_URL`
- `DEBUG`
- `GATE_REAL_INTEGRATION_ENABLED`
- `GATE_MDB_PATH`
- `EXPO_PUBLIC_API_BASE_URL`
- `EXPO_PUBLIC_USE_REAL_API`

### Commands
- Backend tests:
  - `py -3.12 -m pytest -q backend/tests`
- Frontend typecheck:
  - `cd frontend && npm run typecheck`

### Gate MDB setup (real integration)
- Install Python dependency:
  - `py -3.12 -m pip install pyodbc`
- Ensure Microsoft Access Database Engine / ODBC driver is installed.
- Create or recreate `config.mdb`:
  - `py -3.12 -m backend.app.scripts.init_gate_mdb --force`
- Runtime config for backend:
  - `GATE_REAL_INTEGRATION_ENABLED=True`
  - `GATE_MDB_PATH=E:/savoya/SavoyaApp/config.mdb`

### Smoke API flow
1. Login:
   - `POST /api/auth/login`
2. Create pass:
   - `POST /api/requests/`
3. Open access point:
   - `POST /api/access/open`

## Bug Report Template

```
Title:
Environment:
- Backend commit:
- Frontend commit:
- OS:
- API mode (real/mock):

Steps to reproduce:
1.
2.
3.

Expected result:

Actual result:

Logs / payloads:

Screenshots (if UI issue):
```
