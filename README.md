# SavoyaApp

## Текущий режим развертывания
Проект подготовлен для запуска на том же Windows-сервере, где находится Gate `config.mdb`.
Сценарий с bridge/VPS удален.

## Быстрый старт на сервере
1. Установите Python 3.12.
2. Установите зависимости backend:
   - `py -3.12 -m pip install -r backend/requirements.txt`
   - `py -3.12-32 -m pip install pyodbc python-dotenv`
3. Заполните `.env`:
   - `DATABASE_URL=sqlite+aiosqlite:///./backend_prod.db`
   - `DEBUG=False`
   - `GATE_REAL_INTEGRATION_ENABLED=True`
   - `GATE_MDB_PATH=C:/Gate/Server/config.mdb`
   - `GATE_SYSTEMDB_PATH=C:/GATE/Server/Gate.mdw`
   - `GATE_MDB_UID=YOUR_GATE_UID`
   - `GATE_MDB_PWD=YOUR_GATE_PWD`
   - `GATE_WIEGAND_TRANSPORT=dry_run`
4. Запустите backend:
   - `py -3.12 -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000`
5. Проверьте health:
   - `http://127.0.0.1:8000/health`

## Запуск frontend в web-режиме
1. Установите Node.js LTS.
2. Установите зависимости frontend:
   - `cd frontend`
   - `npm install`
3. Запустите web-клиент:
   - `npm run web`
4. Откройте в браузере:
   - `http://localhost:8081`

## Запуск всего стека через Docker
1. Соберите и поднимите сервисы:
   - `docker compose up --build -d`
2. Откройте frontend:
   - `http://localhost`
3. Проверьте backend:
   - `http://localhost:8000/health`

## Команды для проверки
- Backend тесты: `py -3.12 -m pytest -q backend/tests`
- Проверка типов frontend: `cd frontend && npm run typecheck`

## Инструкция на русском: скрипты `config.mdb` и запуск сервера

### 1. Что делают диагностические скрипты
- `scripts/check_gate_mdb.ps1` проверяет, что `config.mdb` открывается, и выводит последние записи из основных таблиц.
- `scripts/find_gate_key.ps1` ищет ключ по цифрам телефона, фрагменту номера карты или машины и выводит связанные права доступа.

### 2. Что должно быть установлено на Windows-сервере
1. Python 3.12 с launcher `py`.
   Для старого Jet/Access `*.mdb` диагностические скрипты по умолчанию запускают `py -3.12-32`.
2. Python-зависимости backend:
   - `py -3.12 -m pip install -r backend/requirements.txt`
3. `pyodbc` для диагностики MDB:
   - `py -3.12-32 -m pip install pyodbc python-dotenv`
4. Microsoft Access Database Engine / ODBC driver для `*.mdb` / `*.accdb`.
   Без Access ODBC драйвера оба PowerShell-скрипта упадут на `pyodbc.connect(...)`.
   Для старой базы Gate предпочтителен драйвер вида `Driver do Microsoft Access (*.mdb)` или `Microsoft Access Driver (*.mdb)`.

### 3. Какой `.env` нужен на сервере
Минимальный рабочий пример:

```env
APP_NAME=GateApp Backend
DEBUG=False
DOCS_ENABLED=False
SECRET_KEY=CHANGE_THIS_TO_A_LONG_RANDOM_SECRET_KEY
ALLOWED_HOSTS_JSON=["203.0.113.10","127.0.0.1","localhost","testserver"]
CORS_ALLOW_ORIGINS_JSON=["http://203.0.113.10","http://127.0.0.1","http://localhost"]
DATABASE_URL=sqlite+aiosqlite:///./backend_test_local.db
BOOTSTRAP_DEMO_USER=False
GATE_REAL_INTEGRATION_ENABLED=True
GATE_MDB_PATH=C:/GATE/Server/config.mdb
GATE_SYSTEMDB_PATH=C:/GATE/Server/Gate.mdw
GATE_MDB_UID=YOUR_GATE_UID
GATE_MDB_PWD=YOUR_GATE_PWD
GATE_ODBC_DRIVER=Driver do Microsoft Access (*.mdb)
GATE_PYTHON_LAUNCHER=py
GATE_PYTHON_VERSION=-3.12-32
GATE_ACTION_MAP_JSON={"entry":19,"exit":20,"wicket_north":15,"wicket_lake":23,"wicket_admin":17,"wicket_forest":21}
DEFAULT_ACCESS_POINT_IDS_JSON=[15,17,19,20,21,23]
GATE_WIEGAND_TRANSPORT=dry_run
EXPO_PUBLIC_USE_REAL_API=true
EXPO_PUBLIC_API_BASE_URL=/api
```

Примечания:
- `GATE_MDB_PATH` должен указывать на реальный файл Gate именно на этом сервере.
- `GATE_SYSTEMDB_PATH` должен указывать на `Gate.mdw`, который используется вместе с `config.mdb`.
- `GATE_MDB_UID` и `GATE_MDB_PWD` нужны для диагностических `ps1`-скриптов, которые читают Gate MDB через ODBC.
- `GATE_ODBC_DRIVER` и `GATE_PYTHON_VERSION` используются и диагностическими `ps1`, и backend bridge для работы с реальным `config.mdb`.
- Для первого запуска используйте `GATE_WIEGAND_TRANSPORT=dry_run`, чтобы приложение не пыталось физически открывать шлагбаум.
- Замените `203.0.113.10` на реальный LAN/public IP сервера.

### 4. Как запустить `check_gate_mdb.ps1`
Из корня проекта `E:\savoya\SavoyaApp` в `cmd.exe`:

```bat
powershell -ExecutionPolicy Bypass -File scripts\check_gate_mdb.ps1 -MdbPath "C:\GATE\Server\config.mdb" -SystemDbPath "C:\GATE\Server\Gate.mdw" -Uid "YOUR_GATE_UID" -Pwd "YOUR_GATE_PWD" -Top 10
```

Если `GATE_MDB_PATH`, `GATE_SYSTEMDB_PATH`, `GATE_MDB_UID` и `GATE_MDB_PWD` уже заданы как системные или пользовательские переменные окружения, можно оставить только `-Top`:

```bat
powershell -ExecutionPolicy Bypass -File scripts\check_gate_mdb.ps1 -Top 10
```

Что должно появиться в выводе:
- `=== Tables ===`
- `=== Readers ===`
- `=== Users ===`
- `=== AccessTable ===`
- `=== AccessZones ===`

Если в каком-то блоке выводится `ERROR: ...`, значит таблица отсутствует или схема реального `config.mdb` отличается от ожидаемой.

### 5. Как запустить `find_gate_key.ps1`
Поиск по фрагменту телефона:

```bat
powershell -ExecutionPolicy Bypass -File scripts\find_gate_key.ps1 -Needle "9261234567" -MdbPath "C:\GATE\Server\config.mdb" -SystemDbPath "C:\GATE\Server\Gate.mdw" -Uid "YOUR_GATE_UID" -Pwd "YOUR_GATE_PWD"
```

Поиск по номеру машины или фрагменту значения карты:

```bat
powershell -ExecutionPolicy Bypass -File scripts\find_gate_key.ps1 -Needle "A123AA"
```

По умолчанию оба скрипта используют `py -3.12-32` и драйвер `Driver do Microsoft Access (*.mdb)`.
Если на конкретном сервере нужны другие значения, переопределите их через `-PythonLauncher`, `-PythonVersion`, `-Driver` или одноимённые переменные окружения.

Что должно появиться в выводе:
- `=== Matching Users ===` с найденными строками из `Users`
- `=== Related Permissions ===` с точками доступа, привязанными к найденным пользователям

### 6. Как запустить backend на сервере
Из корня проекта:

```bat
py -3.12 -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

Проверки после запуска:
- Health: `http://127.0.0.1:8000/health`
- Точки доступа Gate: `http://127.0.0.1:8000/api/gate/access-points`

Важно:
- При старте FastAPI автоматически создает локальные таблицы backend по моделям SQLAlchemy.
- Это не та же база, что `config.mdb`.
- Данные Gate читаются через `GATE_MDB_PATH`, а собственные данные backend хранятся в `DATABASE_URL`.

### 7. Как запустить frontend на сервере
Запуск в web-режиме для разработки:

```bat
cd frontend
npm install
npm run web
```

После этого откройте:
- `http://localhost:8081`

По умолчанию frontend использует тот же origin и путь `/api`, поэтому для продакшена лучше отдавать frontend через Nginx и проксировать `/api` на backend `127.0.0.1:8000`.

### 8. Рекомендуемый прод-запуск на одном Windows-сервере
1. Запустите backend на сервере:
   - `py -3.12 -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000`
2. Опубликуйте frontend через один web-сервер на порту `80`.
3. Проксируйте `/api` на `http://127.0.0.1:8000/api/`.
4. Проксируйте `/health` на `http://127.0.0.1:8000/health`.

Пример конфига Nginx лежит в [deploy/nginx/nginx-ip-only.conf](/e:/savoya/SavoyaApp/deploy/nginx/nginx-ip-only.conf).

### 9. Минимальная проверка после развертывания
1. Откройте `http://SERVER_IP/health` и убедитесь, что видите `{"status":"ok"}`.
2. Запустите `check_gate_mdb.ps1` и убедитесь, что нет ODBC-ошибок и ошибок пути к файлу.
3. Запустите `find_gate_key.ps1 -Needle "..."` для известного жителя или карты и убедитесь, что права доступа находятся.
4. Войдите во frontend и проверьте, что список точек доступа загружается.
5. Держите `GATE_WIEGAND_TRANSPORT=dry_run`, пока не убедитесь, что API и интеграция с MDB работают корректно.
6. Только после этого переключайте транспорт на реальный `http` или `tcp` и проверяйте физическое открытие.

### 10. Типовые проблемы
- `config.mdb not found`
  Проверьте `GATE_MDB_PATH` или передайте правильный путь через `-MdbPath`.
- Ошибка импорта `pyodbc`
  Установите пакет: `py -3.12-32 -m pip install pyodbc python-dotenv`.
- Ошибка ODBC-драйвера для Access
  Установите Microsoft Access Database Engine / Access ODBC driver.
- `TrustedHostMiddleware` блокирует запросы
  Добавьте реальный IP/домен сервера в `ALLOWED_HOSTS_JSON`.
- Frontend открывается, но API не работает
  Проверьте `CORS_ALLOW_ORIGINS_JSON` и reverse proxy для `/api`.
