# Chat Context: Gate Integration and UI Notes

Date: 2026-04-07

## Gate runtime

- The real Gate MDB schema is based on `Users`, `Readers`, and `AccessTable`.
- The old mock-oriented schema `AccessPoints / AccessPermissions / WiegandCredentials` is not valid for the live Gate database.
- Safe read operations must use a temporary copy of `config.mdb` and `Gate.mdw`.
- Backend Gate access now goes through `py -3.12-32` and `backend/app/scripts/gate_bridge.py`.

## Real reader mapping

- `19` -> `Камера Въезда`
- `20` -> `Камера Выезда`
- `15` -> `Считыватель Северная калитка 1`
- `17` -> `Считыватель  калитка 1`
- `21` -> `Вход Лес`
- `23` -> `Вход озеро`

Recommended env values:

```env
GATE_ACTION_MAP_JSON={"entry":19,"exit":20,"wicket_north":15,"wicket_lake":23,"wicket_admin":17,"wicket_forest":21}
DEFAULT_ACCESS_POINT_IDS_JSON=[15,17,19,20,21,23]
GATE_PYTHON_LAUNCHER=py
GATE_PYTHON_VERSION=-3.12-32
GATE_WIEGAND_TRANSPORT=dry_run
```

## Name rules

- For Gate user creation, patronymic is optional.
- `gate_runtime.py` splits the provided name into `LastName`, `FirstName`, and optional `FatherName`.
- Existing rows in the real `Users` table already show that some records have only surname + name, and some records even miss `FirstName`.
- Product decision for the UI: collect `Фамилия и имя`; do not require patronymic.

## Frontend notes

- The create-pass screen should use `Фамилия и имя` instead of `ФИО`.
- The last entered resident name and car number should be remembered locally on the device.
- The user must still be able to overwrite remembered values.
- Each remembered input should have a clear button on the right side.

## Useful commands

From repo root:

```powershell
cd E:\savoya\SavoyaApp
py -3.12 -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Frontend:

```powershell
cd E:\savoya\SavoyaApp\frontend
npm install
npm run typecheck
```

Gate diagnostics:

```powershell
cd E:\savoya\SavoyaApp
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\check_gate_mdb.ps1 -Top 10
.\scripts\find_gate_key.ps1 -Needle "А804АЕ778"
```
